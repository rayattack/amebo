# AMEBO

Amebo is the simplest pubsub server to use, deploy, understand or maintain. It was
built to enable communication between applications i.e. microservices or
modules (if you are using monoliths), and hopes to be able to serve as a small
but capable and simpler alternative to Kafka, RabbitMQ, SQS/SNS.

**STILL IN DEVELOPMENT: NOT READY FOR Production Use**

&nbsp;

## How It Works
---
Amebo has only 4 concepts (first class objects) to understand or master.

&nbsp;

### 1. Applications
---
These can be microservices or modules (in a monolith) - that create and receive notifications about [_**events**_](#2-events). All applications must be registered on
    amebo ;-) before they can publish [_**actions**_](#3-actions).


### 2. Events
---
This is something that can happen in an [_**application**_](#1-applications) i.e. creating a customer, deleting an order. They are registered
    on Amebo by their parent [_**application**_](#1-applications), and all events must provide a valid JSON Schema (can be empty "{}") that Amebo
    can use to validate event actions before sending to [_**subscribers**_](#4-subscribers).


### 3. Actions
---
An action is a HTTP request sent by an [_**application**_](#1-applications) to Amebo to signal it about the occurence of an event locally. Actions
    can have a json payload that must match the JSON Schema of its parent event.

### 4. Subscribers
---
These are HTTP URLs (can be valid hostname for loopback interface on TCP/IP as well) endpoints registered by [_**applications**_](#1-applications) to
    receive [_**action**_](#3-actions) payloads.

&nbsp;


## GETTING STARTED
This assumes you have [installed](https://github.com/tersoo/amebo) Amebo on your machine. Amebo requires [Python3.6+](https://www.python.org/downloads)
```sh
# the easy path
pip install amebo
amebo --workers 2 --address 0.0.0.0:8701


# the hardway (manual installation) BUT not the only way... Sorry, I couldn't resist the pun ;-)
git clone https://github.com/tersoo/amebo
mv amebo /to/a/directory/of/your/choosing
export $PATH=$PATH:/to/a/directory/of/your/choosing/amebo  # add amebo location to your path
ambeo -w 2 -a 0.0.0.0:8701
```

&nbsp;

## 1st : Tell Amebo about all your microservices or applications
---

`endpoint: /v1/microservices`

<table>
<tr>
<th>Schema</th>
<th>Example Payload<th>
</tr>
<tr>
<td>

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

</td>
<td>

```json
{
    "microservice": "customers",
    "passkey": "some-super-duper-secret-of-the-module-or-microservice",
    "location": "http://0.0.0.0:3300"
}
```

</td>
</tr>
</table>


&nbsp;

## 2nd : Register events that can happen in the registered microservices
---

`endpoint: /v1/events`

<table>
<tr>
<th>Endpoint JSON Schema</th>
<th>Example Payload<th>
</tr>
<tr>
<td>

```json
{
    "type": "object",
    "properties": {
        "event": {"type": "string"},
        "microservice": {"type": "string"},
        "schemata": {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "properties": {"type": "object"},
                "required": {"type": "array"}
            }
        }
    },
    "required": ["event", "microservice", "schemata"]
}
```

</td>
<td>

```json
{
    "event": "customers.v1.created",
    "microservice": "customers",
    "schemata": {
        "$id": "https://your-domain/customers/customer-created-schema-example.json",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "customer_id": {"type": "number"},
            "first_name": {"type": "string"},
            "last_name": {"type": "string"},
            "email": {"type": "string", "format": "email"}
        },
        "required": ["customer_id", "email"]
    }
}
```

</td>
</tr>
</table>

&nbsp;

## 3rd : Tell Amebo when an event occurs i.e. create an action
---

`endpoint: /v1/actions`

| Key | Description |
|---|---|
| **event** | Identifier name of the event. (As registered in the previous step.) |
| **deduper** | Deduplication string. used to prevent the same action from being registered twice |
| **payload** | JSON data (must confirm to the schema registerd with the event) |

&nbsp;

<table>
<tr>
<th>Endpoint JSON Schema</th>
<th>Example Payload<th>
</tr>
<tr>
<td>

```json
{
    "type": "object",
    "properties": {
        "event": {"type": "string"},
        "microservice": {"type": "string"},
        "schemata": {
            "type": "string",
            "format": "ipv4 | ipv6 | hostname | idn-hostname"
        },
        "location": {"type": "web"}
    },
    "required": ["microservice", "passkey", "location"]
}
```

</td>
<td>

```json
{
    "event": "customers.v1.created",
    "microservice": "customers",
    "schema": {
        "$id": "https://your-domain/customers/customer-created-schema-example.json",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "event": {"type": "string"},
            "microservice": {"type": "string"},
            "schemata": {"type": "string", "format": "ipv4 | ipv6 | hostname | idn-hostname"},
            "location": {"type": "web"}
        },
        "required": ["microservice", "passkey", "location"]
    },
    "location": "http://0.0.0.0:3300"
}
```

</td>
</tr>
</table>

&nbsp;

## Finally: Create an endpoint to receive action notifications from Amebo
---
Other applications/modules within the same monolith can create handler endpoints that will be sent the payload with optional
encryption if an encryption key was provided by the subscriber when registering for the event.

# Why? Advantages over traditional Message Oriented Middleware(s)

1. Amebo comes complete with a Schema Registry, ensuring actions conform to event schema, and makes it easy for developers to search for events by
    microservice with commensurate schema (i.e. what is required, what is optional) as opposed to meetings with team mates continually.

1. GUI for tracking events, actions, subscribers. Easy discovery of what events exist, what events failed and GUI retry for specific subscribers

1. Gossiping is HTTP native i.e. subscribers receive http requests automatically at pre-registered endpoints

1. Infinite retries (stop after $MAX_RETRIES and $MAX_MINUTES coming soon)


# Trivia

The word `amebo` is a West African (Nigerian origin - but used in Ghana, Benin, Cameroon etc.) slang used to describe anyone that never keeps what you tell them to themselves. A talkative, never mind their business individual (a chronic gossip).
