#!/bin/bash
set -e

# Set timezone from environment or system
if [ -z "$CLIENT_TIMEZONE" ]; then
    CLIENT_TIMEZONE=$(date +"%Z")
fi

echo "Starting ADSB streaming with the following configuration:"
echo "Client ID: $CLIENT_ID"
echo "Client Timezone: $CLIENT_TIMEZONE"
echo "Receiver Location: $LAT, $LON, ALT: $ALT"
echo "Kafka Topic: $TOPIC_NAME"
echo "Bootstrap Server: $CC_BOOTSTRAP"
echo "ADSB Host: $READSB_HOST"

# Wait for Kafka to be ready
echo "Waiting for Kafka to be ready..."
until kafkacat -b $CC_BOOTSTRAP -L; do
  echo "Kafka is unavailable - waiting 10s"
  sleep 10
done
echo "Kafka is ready!"

# Create topic if it doesn't exist
echo "Ensuring topic $TOPIC_NAME exists..."
kafkacat -b $CC_BOOTSTRAP -t $TOPIC_NAME -P -T || echo "Topic already exists or will be auto-created"

# Continuously retry connection if it fails
while true; do
    echo "Connecting to ADSB receiver and streaming data..."
    
    nc $READSB_HOST 30003 \
        | awk -F "," '{ print $5 "|" $0 }' \
        | kafkacat -P \
            -t ${TOPIC_NAME} \
            -b ${CC_BOOTSTRAP} \
            -H "ClientID=${CLIENT_ID}" \
            -H "ClientTimezone=${CLIENT_TIMEZONE}" \
            -H "ReceiverLon=${LON}" \
            -H "ReceiverLat=${LAT}" \
            -H "ReceiverAlt=${ALT}" \
            -K "|" \
            ${CC_SECURE}
            
    echo "Connection lost. Retrying in 10 seconds..."
    sleep 10
done