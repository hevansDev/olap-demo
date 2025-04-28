# consumer-test.py
from confluent_kafka import Consumer, KafkaException
import sys
import logging
import json

# Set up logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration with SASL PLAIN
conf = {
    'bootstrap.servers': 'kafka.hughevans.dev',  # Host IP and port
    'group.id': 'adsb-test-consumer',
    'auto.offset.reset': 'earliest',
    'security.protocol': 'SASL_PLAINTEXT',
    'sasl.mechanism': 'PLAIN',
    'sasl.username': 'consumer',
    'sasl.password': 'consumer-secret',
    'client.id': 'test-consumer'
}

def main():
    # Create Consumer instance
    consumer = Consumer(conf)
    
    # Subscribe to topic
    topic = 'adsb-raw'
    consumer.subscribe([topic])
    
    print(f"Connected to Kafka at {conf['bootstrap.servers']} as user {conf['sasl.username']}")
    print(f"Listening for messages on topic {topic}...")
    
    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
                
            if msg.error():
                if msg.error().code() == KafkaException._PARTITION_EOF:
                    # End of partition event - not an error
                    logger.info(f"Reached end of topic {msg.topic()} partition {msg.partition()}")
                else:
                    logger.error(f"Error: {msg.error()}")
            else:
                # Proper message
                try:
                    # Parse message value
                    value = json.loads(msg.value().decode('utf-8'))
                    print(f"Received message: {value}")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    print(f"Raw message: {msg.value()}")
                    
    except KeyboardInterrupt:
        print("Interrupted by user, shutting down...")
    finally:
        # Close down consumer to commit final offsets.
        consumer.close()
        
if __name__ == "__main__":
    main()