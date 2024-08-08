"""
TODO: change to supersql and group sqlite&pg -> sql so the final option is sql | redis
"""

from constants import PG, REDIS, SQLITE


def register_actions_redis():
    pass


def register_actions_sql():
    pass


def register_applications_redis():...


def register_applications_sql():...


def register_events_redis():
    pass


def register_events_sql():
    pass


def register_subscribers_redis():...


def register_subscribers_sql():...


register_actions = {
    REDIS: register_actions_redis,
    SQLITE: register_actions_sql
}


register_events = {
    REDIS: register_events_redis,
    SQLITE: register_events_sql
}


register_applications = {
    REDIS: register_applications_redis,
    SQLITE: register_applications_sql
}


register_subscribers = {
    REDIS: register_subscribers_redis,
    SQLITE: register_subscribers_sql
}
