#!/bin/bash

# Initialize a flag to track if any configuration was loaded
CONFIG_LOADED=false
CONFIG_FILE="amebo.json"


# First check if --config is specified
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            CONFIG_FILE="$2"
            shift 2
            break
            ;;
        *)
            break
            ;;
    esac
done

# Check if amebo.json exists in current directory
if [ -f "$CONFIG_FILE" ]; then
    # Parse JSON and set environment variables
    while IFS="=" read -r key value; do
        # Remove quotes and spaces from value
        value=$(echo "$value" | sed 's/[",]//g' | sed 's/^ *//g' | sed 's/ *$//g')
        # Skip empty lines and curly braces
        if [[ $key != "{" && $key != "}" && ! -z $key ]]; then
            # Clean up key (remove spaces and quotes)
            key=$(echo "$key" | sed 's/[" ]//g')
            export "$key=$value"
        fi
    done < <(jq -r 'to_entries | .[] | "\(.key)=\(.value)"' "$CONFIG_FILE")
    CONFIG_LOADED=true
else
    # Process command line arguments
    while [[ $# -gt 0 ]]; do
        if [[ $1 == --* ]]; then
            # Remove -- from argument name and convert to uppercase
            key=${1#--}
            key=${key^^}
            value=$2
            export "$key=$value"
            shift 2
            CONFIG_LOADED=true
        else
            shift
        fi
    done
fi

# Check if any configuration was loaded
if [ "$CONFIG_LOADED" = false ]; then
    echo "Error: No configuration provided. Either create amebo.json or provide command line arguments."
    echo "Example usage:"
    echo "  ./amebo.sh --amebo_secret your-secret --amebo_database postgresql://user:pass@localhost/db"
    exit 1
fi

# Validate required environment variables
if [ -z "$AMEBO_SECRET" ]; then
    echo "Error: AMEBO_SECRET is required but not set"
    echo "Please provide it via amebo.json or --amebo_secret argument"
    exit 1
fi

if [ -z "$AMEBO_DATABASE" ]; then
    echo "Error: AMEBO_DATABASE is required but not set"
    echo "Please provide it via amebo.json or --amebo_database argument"
    exit 1
fi

# Start uvicorn
# if no amebo port is set, use 8000
if [ -z "$AMEBO_PORT" ]; then
    AMEBO_PORT=3310
fi

uvicorn amebo.router:router --host 0.0.0.0 --port $AMEBO_PORT
