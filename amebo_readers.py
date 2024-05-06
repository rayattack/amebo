"""
TODO: change to supersql and group sqlite&pg -> sql so the final option is sql | redis
"""

from constants.literals import PG, REDIS, SQLITE


def list_actions_redis():
    pass


def list_actions_sql():
    pass


def list_applications_redis():...


def list_applications_sql():...


def list_events_redis():
    pass


def list_events_sql():
    pass


def list_subscribers_redis():...


def list_subscribers_sql():...


list_actions = {
    REDIS: list_actions_redis,
    SQLITE: list_actions_sql
}


list_events = {
    REDIS: list_events_redis,
    SQLITE: list_events_sql
}


list_applications = {
    REDIS: list_applications_redis,
    SQLITE: list_applications_sql
}


list_subscribers = {
    REDIS: list_subscribers_redis,
    SQLITE: list_subscribers_sql
}
