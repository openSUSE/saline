import logging
import os
import ssl
import tornado
import tornado.log
import tornado.web

from threading import Thread
from time import time, sleep
from tornado.ioloop import IOLoop

from tornado.iostream import StreamClosedError
from salt.transport.ipc import IPCMessageSubscriber
from salt.utils.asynchronous import current_ioloop as ctx_current_ioloop

log = logging.getLogger(__name__)


class SalineChannels:
    def __init__(self, opts):
        self.opts = opts
        self.metrics_buf = None
        self.metrics_last = None
        self.metrics_timeout = opts.get("metrics_timeout", 120)

    def run_channels(self):
        self.io_loop = IOLoop.current()
        self.pub_uri = os.path.join(self.opts["sock_dir"], "publisher.ipc")
        with ctx_current_ioloop(self.io_loop):
            self.subscriber = IPCMessageSubscriber(self.pub_uri, io_loop=self.io_loop)
            self.subscriber.callbacks.add(self.channel_event_handler)
            for _ in range(5):
                try:
                    self.subscriber.connect(callback=self.channel_connected)
                    break
                except StreamClosedError:
                    sleep(1)
            self.io_loop.add_callback(self.subscriber.read_async)

    def channel_connected(self, _):
        log.debug("Connected to Saline publisher channel")
        self.metrics_buf = ""
        self.metrics_last = time()

    def channel_event_handler(self, raw):
        log.trace("Received from Saline publisher: %s", raw)
        if "metrics" in raw:
            self.metrics_buf = raw["metrics"]
            self.metrics_last = time()


class MetricsHandler(tornado.web.RequestHandler):  # pylint: disable=W0223
    def get(self, _):  # pylint: disable=arguments-differ
        if (
            time() - self.application.channels.metrics_last
            > self.application.channels.metrics_timeout
        ):
            log.error(
                "No metrics update for more than %s sec.",
                self.application.channels.metrics_timeout,
            )
            self.send_error(500)
            return
        elif self.application.channels.metrics_buf is not None:
            self.set_header("Cache-Control", "no-cache")
            self.set_header("Content-Type", "text/plain;version=0.0.4;charset=utf-8")
            self.write(self.application.channels.metrics_buf)

        self.finish()


def get_app(opts):
    """
    Returns a Tornado Web APP
    """

    restapi_opts = opts.get("restapi", {})

    paths = [
        (r"/metrics(/.*)?", MetricsHandler),
    ]

    access_log = logging.getLogger("tornado.access")
    access_log.propagate = False
    access_log.setLevel(logging.INFO)

    def tornado_access_log(handler):
        status = handler.get_status()
        request_time = 1000.0 * handler.request.request_time()
        log_level = logging.INFO
        if status >= 500:
            log_level = logging.ERROR
        elif status >= 400:
            log_level = logging.WARNING
        access_log.log(
            log_level,
            '%s - %s "%s %s" %d %s "%s" %.2fms',
            handler.request.remote_ip,
            (
                handler.request.saline_user
                if hasattr(handler.request, "saline_user")
                and handler.request.saline_user
                else "-"
            ),
            handler.request.method,
            handler.request.uri,
            status,
            handler._headers.get("Content-Length", "") or "-",
            handler.request.headers.get("User-Agent", "") or "-",
            request_time,
        )

    access_log_file = restapi_opts.get("log_access_file")
    if access_log_file is not None:
        access_log_handler = logging.FileHandler(access_log_file)
        formatter = logging.Formatter(
            restapi_opts.get(
                "log_access_format",
                "%(asctime)s %(message)s",
            )
        )
    else:
        access_log_handler = logging.StreamHandler()
        formatter = logging.Formatter(
            restapi_opts.get(
                "log_access_format",
                "[%(levelname)-8s] %(message)s",
            )
        )
    access_log_handler.setFormatter(formatter)
    access_log.addHandler(access_log_handler)

    app = tornado.web.Application(
        paths,
        log_function=tornado_access_log,
        debug=restapi_opts.get("debug", False),
    )

    app.channels = SalineChannels(opts)

    return app


def start(opts):
    """
    Start Tornado Web APP
    """

    restapi_opts = opts.get("restapi", {})

    if "num_processes" not in restapi_opts:
        restapi_opts["num_processes"] = 1

    if restapi_opts["num_processes"] > 1 and restapi_opts.get("debug", False) is True:
        raise Exception(
            "Tornado's debug implementation is not compatible with multiprocess. "
            "Either disable debug, or set num_processes to 1."
        )

    # the kwargs for the HTTPServer
    kwargs = {}
    if not restapi_opts.get("disable_ssl", False):
        if "ssl_crt" not in restapi_opts:
            log.error(
                "Not starting '%s'. Options 'ssl_crt' and "
                "'ssl_key' are required if SSL is not disabled.",
            )

            return None
        # cert is required, key may be optional
        # https://docs.python.org/2/library/ssl.html#ssl.wrap_socket
        ssl_opts = {
            "certfile": restapi_opts["ssl_crt"],
            "ssl_version": ssl.PROTOCOL_TLS_SERVER,
        }
        if not os.path.exists(ssl_opts["certfile"]):
            raise Exception(f"Could not find a certificate: {ssl_opts['certfile']}")
        if restapi_opts.get("ssl_key", False):
            ssl_opts.update({"keyfile": restapi_opts["ssl_key"]})
            if not os.path.exists(ssl_opts["keyfile"]):
                raise Exception(
                    f"Could not find a certificate key: {ssl_opts['keyfile']}"
                )
        kwargs["ssl_options"] = ssl_opts

    import tornado.httpserver

    log.debug("Creating Tornado HTTP server ...")
    app = get_app(opts)
    http_server = tornado.httpserver.HTTPServer(app, **kwargs)
    listen_port = restapi_opts.get("port", 8216)
    listen_host = restapi_opts.get("host", "0.0.0.0")
    try:
        log.debug("Binding Tornado HTTP server to %s:%s ...", listen_host, listen_port)
        http_server.bind(
            listen_port,
            address=listen_host,
            backlog=restapi_opts.get("backlog", 128),
        )
        log.debug("Starting Tornado HTTP server ...")
        http_server.start(restapi_opts["num_processes"])
    except Exception:  # pylint: disable=broad-except
        log.error(
            "Tornado Web APP unable to bind to %s:%s",
            listen_host,
            listen_port,
            exc_info=True,
        )
        raise SystemExit(1)

    app.channels.run_channels()
    try:
        IOLoop.current().start()
    except KeyboardInterrupt:
        raise SystemExit(0)


def stop():
    """
    Start Tornado Web APP
    """

    try:
        IOLoop.current().stop()
    except KeyboardInterrupt:
        raise SystemExit(0)
