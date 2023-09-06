# AMEBO

Amebo is the simplest pubsub server to use, deploy, understand or maintain. It was
built to enable communication between applications i.e. microservices or
modules (if you are using monoliths), and can
serve as a full blown replacement for Kafka, RabbitMQ, SQS/SNS.

&nbsp;

### How It Works
-----------------

Amebo has only 4 concepts (first class objects) to understand or master - no long thing.
- Microservices/Modules: These are applications you register on amebo - they send and receive events ;-)
- Action: Something that can happen in an application, they are registered on Amebo by Microservices/Modules
- Subscribers: HTTP endpoints registered by Microservices/Modules to watch specific/particular actions
- Events: An occurence of an action, usually has a payload that is sent to all applications subscribed to the action

&nbsp;


## GETTING STARTED
This assumes you have [installed](https://github.com/tersoo/amebo) Amebo on your machine. Amebo requires [Python3.6+](https://www.python.org/downloads)
```sh
# the easy path
pip install amebo
amebo --workers 2 --address 0.0.0.0:8701


# the hardway (manual installation)
git clone https://github.com/tersoo/amebo
mv amebo /to/a/directory/of/your/choosing
export $PATH=$PATH:/to/a/directory/of/your/choosing/amebo  # add amebo location to your path
ambeo -w 2 -a 0.0.0.0:8701
```

&nbsp;

### 1. Register microservices or applications with a secret key

`endpoint: /v1/microservices`
```json
{
    "microservice": "customers",
    "passkey": "some-super-duper-secret-of-the-module-or-microservice",
    "location": "http://0.0.0.0:3300"
}
```

With the following JSON schema:

```json
{
    "$schema": "",
    "type": "object",
    "properties": {
        "microservice": {"type": "string"},
        "passkey": {"type": "string", "format": "ipv4 | ipv6 | hostname | idn-hostname"},
        "location": {"type": "web"}
    },
    "required": ["microservice", "passkey", "location"]
}
```
&nbsp;

### 2. Add actions to your microservice

&nbsp;

# Why? Advantages over traditional Message Oriented Middleware(s)

1. Amebo comes complete with a Schema Registry, ensuring actions conform to event schema, and makes it easy for developers to search for events by
    microservice with commensurate schema (i.e. what is required, what is optional) as opposed to meetings with team mates continually.

1. GUI for tracking events, actions, subscribers. Easy discovery of what actions exist, what events failed and GUI retry for specific subscribers

1. Gossiping is HTTP native i.e. subscribers receive gossips at pre-registered endpoints

1. Infinite retries (stop after $MAX_RETRIES and $MAX_MINUTES coming soon)


# Trivia

The word `amebo` is a West African (Nigeria, Ghana, Benin, Cameroon) slang used to describe a chronic gossip. An `amebo` snitches about everything.
