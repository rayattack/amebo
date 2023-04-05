initdbscript = '''
BEGIN;
    CREATE TABLE IF NOT EXISTS microservices (
        microservice varchar(128) primary key,
        location varchar(512) not null,
        passkey text not null,
        timestamped varchar(32) not null
    );

    CREATE TABLE IF NOT EXISTS events (
        event varchar(128) primary key not null,
        microservice varchar(128) NOT NULL REFERENCES microservices(microservice),
        schemata text not null,
        timestamped varchar(32) not null
    );

    CREATE TABLE IF NOT EXISTS actions (
        action integer primary key not null,
        event varchar(128) not null references events(event),
        deduper varchar(128) not null,
        payload text not null,
        timestamped varchar(32) not null,

        UNIQUE(deduper, payload)
    );

    CREATE TABLE IF NOT EXISTS subscribers (
        subscriber integer primary key not null,
        microservice varchar(128) not null references microservices(microservice),
        event varchar(128) not null references events(event),
        endpoint varchar(256) not null,
        description text not null,
        timestamped varchar(32) not null,

        UNIQUE(microservice, event, endpoint)
    );

    CREATE TABLE IF NOT EXISTS gists (
        action integer references actions(action),
        subscriber integer references subscribers(subscriber),
        completed integer not null,
        timestamped varchar(32) not null,

        UNIQUE(action, subscriber)
    );
COMMIT;
'''

tidydatabase = '''
    CREATE TRIGGER IF NOT EXISTS
        prune_gists
    AFTER INSERT ON
        gists
    WHEN
        count(*) > 1_000_000
    BEGIN
        DELETE FROM gists WHERE timestamped < '14 days ago'
    END
'''
