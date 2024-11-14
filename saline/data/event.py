import logging
import re


from saline.data.parser import (
    get_tag_mask,
    get_timestamp,
    get_trimmed,
    parse_duration,
    parse_state_fun_args,
    split_state_tags,
    EventTags,
    IGNORE_EVENTS,
    IGNORE_NO_FUN_WARNING,
    STATE_FUNCS,
    STATE_RESULTS,
)


log = logging.getLogger(__name__)


class EventParser:
    """
    Salt Event Parser object
    """

    def __init__(self, opts):
        """
        Create a Salt Event Parser object instance
        """

        self.sls_rules = []
        self.sid_rules = []
        self.mod_rules = []

        for rule_set in ("sls", "sid", "mod"):
            dst_list = getattr(self, f"{rule_set}_rules")
            for k, v in opts.get("rename_rules", {}).get(rule_set, {}).items():
                dst_list.append((re.compile(k), v))

    def __rule_merge(self, rule_set, v):
        for p, r in getattr(self, f"{rule_set}_rules"):
            if p.match(v):
                return r
        return v

    def parse(self, tag, data):
        """
        Parse Salt Event data
        """

        fun = data.get("fun")
        tag_mask, tag_main, tag_sub, tag_minion_id = get_tag_mask(tag, return_all=True, return_minion_id=True)

        if tag_minion_id is not None and "id" not in data:
            data["id"] = tag_minion_id

        if tag_main == EventTags.SALT_KEY and fun is None:
            fun = data.get("act")

        if fun is None and (tag_main, tag_sub) not in IGNORE_NO_FUN_WARNING:
            log.warning(
                "Ignore the event as there is no function specified in the data: (%s) %s",
                tag,
                data,
            )
            return

        if (tag_main, tag_sub, fun) in IGNORE_EVENTS:
            return

        ts = get_timestamp(data.get("_stamp"))

        parsed_data = {
            "tag": tag,
            "tag_mask": tag_mask,
            "ts": ts,
        }

        if "minions" in data and not isinstance(data["minions"], list):
            log.warning("Minions list is malformed: (%s): %s", tag, data["minions"])

        if "jid" in data:
            jid = data["jid"]
            try:
                jid = int(jid)
            except ValueError:
                pass
            parsed_data["jid"] = jid

        for key in ("id", "user", "minions", "success"):
            if key in data:
                parsed_data[key] = data[key]

        for key, src in (("fun", fun), ("tag_main", tag_main), ("tag_sub", tag_sub)):
            if src is not None:
                parsed_data[key] = src

        trimmed = list(get_trimmed(data))
        if trimmed:
            parsed_data["trimmed"] = trimmed

        if tag_main == EventTags.SALT_BATCH and tag_sub in (
            EventTags.SALT_BATCH_START,
            EventTags.SALT_BATCH_DONE,
        ):
            parsed_data["down_minions"] = data.get("down_minions", [])

        retcode = data.get("retcode")
        if (
            tag_main == EventTags.SALT_JOB
            and tag_sub in (EventTags.SALT_JOB_NEW, EventTags.SALT_JOB_RET)
            and retcode is not None
            and retcode == 255
            and data.get("stderr")
        ):
            parsed_data["offline"] = True
            log.debug(
                "Considering response from '%s' ssh minion on jid: %s as offline status",
                data.get("id"),
                data.get("jid"),
            )

        if (
            tag_main == EventTags.SALT_JOB
            and tag_sub in (EventTags.SALT_JOB_NEW, EventTags.SALT_JOB_RET)
            and fun
            and fun.startswith("state.")
        ):
            fun_args = data.get("fun_args", data.get("arg", None))
            if fun_args is not None:
                args, kwargs = parse_state_fun_args(fun_args)
                args = (
                    *[
                        self.__rule_merge("mod", x) for x in args
                    ],
                )
                parsed_data["state_fun_args"] = (
                    fun,
                    args,
                    kwargs.get("test", False) is True,
                )
                if (kwargs.get("test", False) is True) or fun == "state.test":
                    parsed_data["test"] = True

        if (
            tag_main == EventTags.SALT_JOB
            and tag_sub == EventTags.SALT_JOB_RET
            and fun in STATE_FUNCS
            and "return" in data
            and isinstance(data["return"], (dict, list))
        ):
            if isinstance(data["return"], dict):
                nchanges = 0
                duration = 0
                rcounts = {}
                for rtag in data["return"].keys():
                    ret = data["return"][rtag]
                    if not isinstance(ret, dict):
                        continue
                    nchanges += 1 if ret.get("changes") else 0
                    state_id, state_fun, state_name = split_state_tags(
                        rtag, ret.get("name")
                    )
                    if state_name and "name" not in ret:
                        ret["name"] = state_name
                    sls = ret.get("__sls__")
                    if sls:
                        _sls = sls.replace("/", ".")
                        _sls = self.__rule_merge("sls", _sls)
                        if sls != _sls:
                            ret["__sls__"] = _sls
                            ret["__sls_orig__"] = sls
                    sid = ret.get("__id__", state_id)
                    if sid:
                        if "__id__" not in ret:
                            ret["__id__"] = sid
                        _sid = self.__rule_merge("sid", sid)
                        if sid != _sid:
                            ret["__id__"] = _sid
                            ret["__id_orig__"] = sid
                    ret["fun"] = state_fun
                    result = ret.get("result")
                    if ret.get("__state_ran__") is False:
                        ret.pop("__state_ran__", None)
                        result = None
                    rcounts.setdefault(result, 0)
                    rcounts[result] += 1
                    if "warnings" in ret:
                        rcounts.setdefault("warnings", 0)
                        rcounts["warnings"] += 1
                    ret.pop("start_time", None)
                    dur = parse_duration(ret.get("duration", 0))
                    if dur is not None:
                        ret["duration"] = dur
                        duration += dur
                parsed_data["duration"] = duration
                for result, key in STATE_RESULTS:
                    if result in rcounts:
                        parsed_data[key] = rcounts[result]
                parsed_data["changes"] = nchanges
            elif isinstance(data["return"], str):
                parsed_data["changes"] = 1
            elif isinstance(data["return"], list):
                parsed_data["errors"] = len(data["return"])
            parsed_data["return"] = data["return"]

        if tag_main == EventTags.SALT_STATS:
            parsed_data["stats"] = data.get("stats", {})

        return parsed_data
