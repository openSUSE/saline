import contextlib
import logging
import os
import re
import signal
import sys

import salt.ext.tornado.gen
import salt.syspaths
import salt.utils.files

from multiprocessing import Pipe, Queue
from threading import Thread, Lock
from time import time, sleep
from queue import Empty as QueueEmpty

from saline import restapi
from saline.data.event import EventParser
from saline.data.merger import DataMerger

from salt.ext.tornado.ioloop import IOLoop, PeriodicCallback
from salt.transport.ipc import IPCMessagePublisher
from salt.utils.event import get_event
from salt.utils.process import (
    ProcessManager,
    SignalHandlingProcess,
    default_signals,
)

log = logging.getLogger(__name__)


class Saline(SignalHandlingProcess):
    """
    The Saline main process
    """

    def __init__(self, opts, **kwargs):
        """
        Create a Saline Events Collector instance

        :param dict opts: The Saline options
        """

        super().__init__()

        self.opts = opts
        self.req_queue = Queue()
        self.ret_queue = Queue()

    def start(self):
        """
        Start the main Saline routine
        """

        with default_signals(signal.SIGINT, signal.SIGTERM):
            log.info("Creating process manager")
            self.process_manager = ProcessManager(wait_for_kill=5)

            self.process_manager.add_process(
                EventsManager,
                args=(
                    self.opts,
                    self.req_queue,
                ),
            )
            self.process_manager.add_process(
                DataManager,
                args=(
                    self.opts,
                    self.ret_queue,
                ),
            )
            for i in range(int(self.opts["readers_subprocesses"])):
                self.process_manager.add_process(
                    EventsReader,
                    args=(
                        self.opts,
                        self.req_queue,
                        self.ret_queue,
                        i,
                    ),
                )
            self.process_manager.add_process(
                TornadoSrv,
                args=(self.opts,),
            )

        # Install the SIGINT/SIGTERM handlers if not done so far
        if signal.getsignal(signal.SIGINT) is signal.SIG_DFL:
            # No custom signal handling was added, install our own
            signal.signal(signal.SIGINT, self._handle_signals)

        if signal.getsignal(signal.SIGTERM) is signal.SIG_DFL:
            # No custom signal handling was added, install our own
            signal.signal(signal.SIGTERM, self._handle_signals)

        self.process_manager.run()

    def _handle_signals(self, signum, sigframe):
        # escalate the signals to the process manager
        self.process_manager._handle_signals(signum, sigframe)
        sleep(1)
        sys.exit(0)


class EventsManager(SignalHandlingProcess):
    """
    The Saline Events Manager process
    """

    def __init__(self, opts, queue, **kwargs):
        """
        Create a Saline Events Manager instance

        :param dict opts: The Saline options
        :param Queue queue: The queue to put the captured events to
        """

        super().__init__()

        self.name = "EventsManager"

        self.event_bus = None

        self.opts = opts
        self.queue = queue

        self.mopts = None

        self._salt_events = None

        self._int_queue = []
        self._int_queue_exit = False

        self._last_reconnect = 0

    def process_events(self):
        events_filter_re = re.compile(self.opts["events_regex_filter"])
        events_additional = []
        for add_filter in self.opts.get("events_additional", []):
            events_additional.append(re.compile(add_filter))

        while True:
            if self._int_queue_exit:
                break
            sleep(0.2)
            while self._int_queue:
                tag, event = self._int_queue.pop(0)

                if not isinstance(event, dict):
                    continue

                if events_filter_re.match(tag):
                    self.queue.put((tag, event))
                    continue

                in_additional = False
                for filter_re in events_additional:
                    if filter_re.match(tag):
                        in_additional = True
                        break
                if in_additional:
                    self.queue.put((tag, event))
                    continue

                log.debug("The event tag doesn't match the event filter: %s", tag)

    @salt.ext.tornado.gen.coroutine
    def enqueue_event(self, raw):
        try:
            self._int_queue.append(self.event_bus.unpack(raw))
        except:  # pylint: disable=broad-except
            # Just to ignore any possible exceptions on unpacking data
            pass

    def _init_event_bus(self):
        if self.event_bus is not None:
            self.event_bus.destroy()
        self.event_bus = get_event(
            "master",
            listen=True,
            io_loop=self.io_loop,
            opts=self.mopts,
            raise_errors=False,
            keep_loop=True,
        )
        self.event_bus.set_event_handler(self.enqueue_event)

    @salt.ext.tornado.gen.coroutine
    def _check_connected(self):
        if (
            not self.event_bus.subscriber.connected()
            and self._last_reconnect + 10 < time()
        ):
            log.warning("Event subscriber stream is not connected. Reconnecting...")
            self._last_reconnect = time()
            self._init_event_bus()

    def run(self):
        """
        Saline Events Manager routine capturing the events from Sale Event Bus
        """

        log.info("Running Saline Events Manager")

        conf_path = os.path.join(salt.syspaths.CONFIG_DIR, "master")

        log.debug("Reading the config: %s", conf_path)
        self.mopts = salt.config.client_config(conf_path)

        log.debug(
            "Starting reading salt events from: %s (%s)",
            self.mopts["sock_dir"],
            self.mopts["transport"],
        )

        self._int_queue_thread = Thread(target=self.process_events)
        self._int_queue_thread.start()

        self.io_loop = IOLoop(make_current=True)
        self._init_event_bus()
        self._check_connected_cb = PeriodicCallback(
            self._check_connected, 3000, io_loop=self.io_loop
        )
        self._check_connected_cb.start()
        self.io_loop.start()

    def _handle_signals(self, signum, sigframe):
        if self._salt_events is not None:
            self._salt_events.close()
        self.io_loop.stop()
        if self._int_queue_thread is not None:
            self._int_queue_exit = True
            self._int_queue_thread = None
        sys.exit(0)


class DataManager(SignalHandlingProcess):
    """
    The Saline Data Manager process
    """

    def __init__(self, opts, queue, **kwargs):
        """
        Create a Saline Data Manager instance

        :param dict opts: The Saline options
        :param Queue queue: The queue to get the processed events from
        """

        super().__init__()

        self.name = "DataManager"

        self.opts = opts
        self.queue = queue

        self.metrics_epoch = None
        self.datamerger = None

        self.datamerger_thread = None
        self.maintenance_thread = None

        self._close_lock = Lock()

    def run(self):
        """
        Saline Data Manager routine merging the processed events to the Data Merger
        """

        log.info("Running Saline Data Manager")

        self.datamerger = DataMerger(self.opts)

        self._stop_datamerger = False
        self.datamerger_thread = Thread(target=self.start_datamerger)
        self.datamerger_thread.start()

        self._job_timeout_check_interval = self.opts.get(
            "job_timeout_check_interval", 120
        )
        self._job_timeout = self.opts.get("job_timeout", 1200)
        self._job_metrics_update_interval = self.opts.get(
            "job_metrics_update_interval", 5
        )

        self._job_jids_cleanup_interval = self.opts.get("job_jids_cleanup_interval", 30)

        self._maintenance_stop = False
        self.maintenance_thread = Thread(target=self.start_maintenance)
        self.maintenance_thread.start()

        self.start_server()

    def _handle_signals(self, signum, sigframe):
        self.stop_datamerger()
        self.stop_maintenance()
        self.stop_server()
        sys.exit(0)

    def start_datamerger(self):
        while True:
            if self._stop_datamerger:
                break
            try:
                data = self.queue.get(timeout=0.2)
            except QueueEmpty:
                continue
            except (ValueError, OSError):
                break
            self.datamerger.add(data)

    def stop_datamerger(self):
        if self.datamerger_thread is not None:
            self._stop_datamerger = True
            self.datamerger_thread = None

    def start_maintenance(self):
        ts = time()
        run_complete_after = ts + self._job_timeout_check_interval
        run_job_metrics_update_after = ts + self._job_metrics_update_interval
        run_job_jids_cleanup_after = ts + self._job_jids_cleanup_interval
        while True:
            sleep(0.2)
            if self._maintenance_stop:
                break
            ts = time()
            if ts > run_complete_after:
                run_complete_after = ts + self._job_timeout_check_interval
                self.datamerger.jobs.complete_with_timeout(self._job_timeout, ts=ts)
            if ts > run_job_metrics_update_after:
                run_job_metrics_update_after = ts + self._job_metrics_update_interval
                self.datamerger.jobs_metrics_update()
            if ts > run_job_jids_cleanup_after:
                run_job_jids_cleanup_after = ts + self._job_jids_cleanup_interval
                self.datamerger.cleanup_job_jids()

    def stop_maintenance(self):
        if self.maintenance_thread is not None:
            self._maintenance_stop = True
            self.maintenance_thread = None

    def start_server(self):
        self.io_loop = IOLoop()
        with salt.utils.asynchronous.current_ioloop(self.io_loop):
            pub_uri = os.path.join(self.opts["sock_dir"], "publisher.ipc")
            self.publisher = IPCMessagePublisher(
                {"ipc_write_buffer": self.opts.get("ipc_write_buffer", 0)},
                pub_uri,
                io_loop=self.io_loop,
            )
            with salt.utils.files.set_umask(0o177):
                self.publisher.start()
            self.io_loop.add_callback(self.metrics_publisher)
            try:
                self.io_loop.start()
            except KeyboardInterrupt:
                sys.exit(0)

    def stop_server(self):
        with self._close_lock:
            if self.publisher is not None:
                self.publisher.close()
                self.publisher = None
            if self.io_loop is not None:
                self.io_loop.close()
                self.io_loop.stop()
                self.io_loop = None

    @salt.ext.tornado.gen.coroutine
    def metrics_publisher(self):
        last_update = time()
        while True:
            epoch = self.datamerger.get_metrics_epoch()
            cur_time = time()
            if (
                epoch != self.metrics_epoch
                or self.metrics_epoch is None
                or cur_time - last_update > 110
            ):
                self.metrics_epoch = epoch
                last_update = cur_time
                self.publisher.publish({"metrics": self.datamerger.get_metrics()})
            yield salt.ext.tornado.gen.sleep(3)


class EventsReader(SignalHandlingProcess):
    """
    The Saline Events Reader process
    """

    def __init__(self, opts, req_queue, ret_queue, idx, **kwargs):
        """
        Create a Saline Events Reader instance

        :param dict opts: The Saline options
        :param Queue queue: The queue to put the captured events to
        """

        super().__init__()

        self._idx = idx
        self.name = "EventsReader-%s" % idx

        self.opts = opts
        self.req_queue = req_queue
        self.ret_queue = ret_queue

        self._exit = False

        self.event_parser = EventParser(self.opts)

    def run(self):
        """
        Saline Events Reader routine processing the captured Salt Events
        """

        log.info("Running Saline Events Reader: %s", self.name)

        while True:
            if self._exit:
                break
            try:
                event = self.req_queue.get(timeout=0.5)
            except QueueEmpty:
                continue
            except (ValueError, OSError):
                break
            parsed_data = self.event_parser.parse(*event)
            if parsed_data is not None:
                parsed_data["rix"] = self._idx
                self.ret_queue.put(parsed_data)

    def _handle_signals(self, signum, sigframe):
        self._exit = True
        sys.exit(0)


class TornadoSrv(SignalHandlingProcess):
    """
    The Saline Tornado Server process
    """

    def __init__(self, opts, **kwargs):
        """
        Create a Saline Tornado Server instance

        :param dict opts: The Saline options
        """

        super().__init__()

        self.name = "TornadoSrv"

        self.opts = opts

    def run(self):
        """
        Turn on the Saline Tornado Server components
        """

        log.info("Running Saline Tornado Server")

        apiopts = self.opts.get("restapi", {})

        if not apiopts.get("disable_ssl", False):
            if "ssl_crt" not in apiopts or "ssl_key" not in apiopts:
                log.error(
                    "Not starting Saline Tornado Server. Options 'ssl_crt' and "
                    "'ssl_key' are required if SSL is not disabled."
                )
                return None

        if "ssl_crt" in apiopts and "ssl_key" in apiopts:
            self.verify_certs(apiopts["ssl_crt"], apiopts["ssl_key"])

        restapi.start(self.opts)

    def verify_certs(self, *cert_files):
        """
        Sanity checking for the specified SSL certificates
        """

        for cert_file in cert_files:
            if not os.path.exists(cert_file):
                raise Exception("Could not find a certificate: {}".format(cert_file))

    def _handle_signals(self, signum, sigframe):
        self.stop_tornado()
        sys.exit(0)

    def stop_tornado(self):
        logging.raiseExceptions = False
        restapi.stop()
