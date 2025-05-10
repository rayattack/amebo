# AMEBO
Amebo is a schema registry, and event broadcast runtime that enables you to disconnect your applications from PubSub/RabbitMQ/Kafka/SQS and other such queue/messaging
systems. It provides a simple API for you to register event schemas, submit message payloads for broadcast to queues/pubsub servers or
other web applications.
Amebo is built to enable communication between applications i.e. microservices or
modules (if you are using monoliths) collectively called **applications**.


1. Availability: Amebo runs on battle tested open source tools i.e. Postgres/MySQL/SQLite and provides the same level of availability guarantees provided by the backing storage system.

1. Reliability: Amebo has been used at scale by open source projects to handle 100's of millions of request

1. Latency: Amebo guarantees sub 10ms latencies at scale (barring network and hardware limitations)

1. Amebo supports a couple of backend engines including but not limited to PubSub, Kafka, RabbitMQ, and SQS.

&nbsp;

## How It Works
---
Amebo has only 4 concepts (first class objects) to understand or master.

&nbsp;

### 1. Applications
---
These can be microservices or modules (in a monolith) - that create and receive notifications about [_**events**_](#2-events). All applications must be registered on
    amebo ;-) before they can publish [_**events**_](#3-events).


### 2. Actions
---
This is something that can happen in an [_**application**_](#1-applications) i.e. creating a customer, deleting an order. They are registered
on Amebo by their parent [_**application**_](#1-applications), and all actions must provide a valid JSON Schema (can be empty "{}") that Amebo
can use to validate action events before sending to [_**subscribers**_](#4-subscribers).

Actions map to topics in Kafka, PubSub etc.


### 3. Events
---
An event is the occurence of an action and in practice is a HTTP request sent by an [_**application**_](#1-applications) to Amebo to signal it about the
occurence of an action locally. Events can have a json payload that must match the JSON Schema of its parent action.


### 4. Subscriptions
---
These are HTTP URLs (can be valid hostname for loopback interface on TCP/IP as well) endpoints registered by [_**applications**_](#1-applications) to
receive [_**action**_](#3-actions) payloads.


&nbsp;


## GETTING STARTED

### Build
This assumes you have [installed](https://github.com/tersoo/amebo) Amebo on your machine. Amebo requires [Python3.6+](https://www.python.org/downloads)
```sh
# the easy path
pip install amebo
amebo --workers 2 --address 0.0.0.0:8701


# the hardway (manual installation) BUT not the only way... Sorry, I couldn't resist the pun ;-)
git clone https://github.com/tersoo/amebo
mv amebo /to/a/directory/of/your/choosing
export $PATH=$PATH:/to/a/directory/of/your/choosing/amebo  # add amebo location to your path
amebo -w 2 -a 0.0.0.0:8701
```

#### Docker


&nbsp;


## 1st : Tell Amebo about all the applications it should tattle about
---

`endpoint: /v1/applications`

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
        "application": {"type": "string"},
        "secret": {"type": "string"},
        "address": {"type": "web", "format": "ipv4 | ipv6 | hostname | idn-hostname"}
    },
    "required": ["application", "secret", "address"]
}
```

</td>
<td>

```json
{
    "application": "customers",
    "secret": "some-super-duper-secret-of-the-module-or-application-or-microservice",
    "address": "http://0.0.0.0:3310"
}
```

</td>
</tr>
</table>


&nbsp;

## 2nd : Register actions that can happen in the registered producers
---

`endpoint: /v1/actions`

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
        "action": {"type": "string"},
        "application": {"type": "string"},
        "schemata": {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "properties": {"type": "object"},
                "required": {"type": "array"}
            }
        }
    },
    "required": ["action", "application", "schemata"]
}
```

</td>
<td>

```json
{
    "action": "customers.v1.created",
    "application": "customers",
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

## 3rd : Tell Amebo when an action occurs i.e. create an event
---

`endpoint: /v1/events`

| Key | Description |
|---|---|
| **action** | Identifier name of the action. (As registered in the previous step.) |
| **deduper** | Deduplication string. used to prevent the same event from being registered twice |
| **payload** | JSON data (must confirm to the schema registerd with the action) |

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
        "application": {"type": "string"},
        "schemata": {
            "type": "string",
            "format": "ipv4 | ipv6 | hostname | idn-hostname"
        },
        "location": {"type": "web"}
    },
    "required": ["application", "secret", "location"]
}
```

</td>
<td>

```json
{
    "event": "customers.v1.created",
    "application": "customers",
    "schema": {
        "$id": "https://your-domain/customers/customer-created-schema-example.json",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "event": {"type": "string"},
            "application": {"type": "string"},
            "schemata": {"type": "string", "format": "ipv4 | ipv6 | hostname | idn-hostname"},
            "location": {"type": "web"}
        },
        "required": ["application", "secret", "location"]
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
Other applications/microservices/modules within the same monolith can create handler endpoints that will be sent
the payload with optional encryption if an encryption key was provided by the subscriber when registering for
the event.

# Why? Advantages over traditional Message Oriented Middleware(s)

1. Amebo comes complete with a Schema Registry, ensuring actions conform to event schema, and makes it easy for
developers to search for events by application(s) with commensurate schema (i.e. what is required, what is optional) as opposed to meetings with team mates continually.

1. GUI for tracking events, actions, subscribers. Easy discovery of what actions exist, what events failed and GUI retry for specific subscribers

1. Gossiping is HTTP native i.e. subscribers receive http requests automatically at pre-registered endpoints

1. Envelope format and transmission is web native and clearly outlined by schema registry

1. Topic management is simplified as actions with versioning support baked in

1. Infinite retries (stop after $MAX_MINUTES coming soon) EDITED: Stop after $MAX_RETRIES implemented


# Trivia

The word `amebo` is a West African (Nigerian origin - but used in Ghana, Benin, Cameroon etc.) slang used to describe anyone that never keeps what you tell them to themselves. A talkative, never mind their business individual (a chronic gossip).
