"""Editable demonstration input metadata only; never authority or expected output."""


def registered_example_observations():
    return {
        "D-104": {
            "world_time": "2026-10-04T09:00:00+00:00",
            "observations": [
                {"metric_key": "apex_on_time_rate", "value": 0.987, "unit": "ratio",
                 "window_days": 30, "observed_at": "2026-10-04T09:00:00+00:00"},
                {"metric_key": "beacon_reactivation_days", "value": 70, "unit": "days",
                 "window_days": None, "observed_at": "2026-10-04T09:00:00+00:00"},
            ],
        },
        "D-205": {
            "world_time": "2026-09-08T12:00:00+00:00",
            "observations": [
                {"metric_key": "release_error_rate", "value": 0.06, "unit": "ratio",
                 "window_days": 1, "observed_at": "2026-09-08T12:00:00+00:00"},
                {"metric_key": "rollback_restore_success_rate", "value": 0.8, "unit": "ratio",
                 "window_days": 1, "observed_at": "2026-09-08T12:00:00+00:00"},
            ],
        },
    }
