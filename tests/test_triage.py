from agent import triage


def pod(name, state=None, last=None, restarts=0, conditions=None):
    return {
        "metadata": {"name": name},
        "status": {
            "conditions": conditions or [],
            "containerStatuses": [
                {
                    "name": "app",
                    "state": state or {"running": {}},
                    "lastState": last or {},
                    "restartCount": restarts,
                }
            ],
        },
    }


def test_healthy_pod_has_no_problems():
    assert triage.pod_problems({"items": [pod("a")]}) == []


def test_detects_crashloop_oom_and_image_pull():
    pods = {
        "items": [
            pod(
                "crash",
                {"waiting": {"reason": "CrashLoopBackOff", "message": "back-off"}},
            ),
            pod("oom", last={"terminated": {"reason": "OOMKilled", "exitCode": 137}}),
            pod("pull", {"waiting": {"reason": "ImagePullBackOff"}}),
            pod(
                "starting", {"waiting": {"reason": "ContainerCreating"}}
            ),  # normal, not a problem
        ]
    }
    assert triage.pod_problems(pods) == [
        "crash: CrashLoopBackOff back-off",
        "oom: last run ended OOMKilled (exit code 137)",
        "pull: ImagePullBackOff",
    ]


def test_detects_unschedulable_pod():
    cond = [
        {"type": "PodScheduled", "status": "False", "message": "Insufficient memory"}
    ]
    assert triage.pod_problems({"items": [pod("p", conditions=cond)]}) == [
        "p: cannot be scheduled (Insufficient memory)"
    ]


def test_debounce_reports_once_after_two_failing_runs():
    state, report = triage.next_state(None, "abc", failing=True)
    assert (state, report) == ("seen:abc", False)  # first sighting: wait
    state, report = triage.next_state(state, "abc", failing=True)
    assert (state, report) == ("abc", True)  # still failing: report
    state, report = triage.next_state(state, "abc", failing=True)
    assert (state, report) == ("abc", False)  # already reported
    assert triage.next_state("abc", "def", failing=True) == (
        "seen:def",
        False,
    )  # new commit: start over


def test_transient_failure_is_never_reported():
    state, _ = triage.next_state(None, "abc", failing=True)
    assert triage.next_state(state, "abc", failing=False) == (None, False)


def test_warning_events_newest_last():
    events = {
        "items": [
            {
                "type": "Warning",
                "reason": "BackOff",
                "message": "restarting",
                "count": 3,
                "lastTimestamp": "2",
            },
            {
                "type": "Normal",
                "reason": "Pulled",
                "message": "ok",
                "lastTimestamp": "3",
            },
            {
                "type": "Warning",
                "reason": "Failed",
                "message": "pull error",
                "lastTimestamp": "1",
            },
        ]
    }
    assert triage.warning_events(events) == [
        "Failed: pull error (x1)",
        "BackOff: restarting (x3)",
    ]


def test_render_with_and_without_ai():
    ai = {
        "root_cause": "Model file missing.",
        "fix": "Fix MODEL_PATH.",
        "confidence": "high",
    }
    body = triage.render(7, "abcdef123", ["p: CrashLoopBackOff"], "logs", ai, "")
    assert "preview `pr-7` is failing" in body and "Commit `abcdef1`" in body
    assert "(high confidence)" in body and "**Suggested fix:** Fix MODEL_PATH." in body
    fallback = triage.render(
        7, "abcdef123", ["p: CrashLoopBackOff"], "logs", None, "TimeoutError"
    )
    assert (
        "AI diagnosis unavailable (TimeoutError)" in fallback
        and "- p: CrashLoopBackOff" in fallback
    )
