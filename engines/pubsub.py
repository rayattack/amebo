from typing import Callable
from google.cloud import pubsub_v1


class Pubsub(object):
    def __init__(self):
       self._ordered = None  # if ordering key provided it will be saved here
       publisher = pubsub_v1.PublisherClient()
       topic_path = publisher.topic_path('my-project-id', 'my-topic-id')
       self.publisher = publisher
       self.topic_path = topic_path

    @property
    def ordered(self):
        """The ordered property."""
        return self._ordered

    @ordered.setter
    def ordered(self, value):
        self._ordered = value
    
    def emit(topic: str, message: dict):
        self.publisher.publish(self.topic_path(topic), message, origin = 'sample', username = 'username')

    def watch(topic: str, func: Callable):
        pass

    def filter(topic: str, attribute: str, value: str):
        pass

