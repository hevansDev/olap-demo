import socket
import time
from confluent_kafka import Producer, KafkaException, KafkaError
from confluent_kafka.admin import AdminClient, NewTopic
import json
import datetime
import os
from dotenv import load_dotenv

# More detailed logging
import logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Configure connection to SBS output from Ultrafeeder
SBS_HOST = os.getenv('SBS_HOST', 'ultrafeeder')
SBS_PORT = int(os.getenv('SBS_PORT', 30003))

# Configure connection to Kafka with SASL authentication
KAFKA_BROKER = os.getenv('KAFKA_BROKER', 'broker:29093')
KAFKA_TOPIC = os.getenv('TOPIC_NAME', 'adsb-raw')

# Load credentials from environment variables
KAFKA_USERNAME = os.getenv('KAFKA_PRODUCER_USERNAME', 'producer')
KAFKA_PASSWORD = os.getenv('KAFKA_PRODUCER_PASSWORD', 'producer-secret')

def ensure_topic_exists():
    """Ensure that the Kafka topic exists"""
    conf = {
        'bootstrap.servers': KAFKA_BROKER,
        'security.protocol': 'SASL_PLAINTEXT',
        'sasl.mechanism': 'PLAIN',
        'sasl.username': KAFKA_USERNAME,
        'sasl.password': KAFKA_PASSWORD
    }
    
    try:
        admin_client = AdminClient(conf)
        topic_list = [NewTopic(KAFKA_TOPIC, num_partitions=1, replication_factor=1)]
        
        # Create topics
        fs = admin_client.create_topics(topic_list)
        
        # Wait for operation to complete
        for topic, f in fs.items():
            try:
                f.result()  # The result itself is None
                logger.info(f"Created topic: {topic}")
            except KafkaException as e:
                if e.args[0].code() == KafkaError.TOPIC_ALREADY_EXISTS:
                    logger.info(f"Topic {topic} already exists")
                else:
                    logger.error(f"Failed to create topic {topic}: {e}")
    except Exception as e:
        logger.error(f"Error creating topic: {e}")

def connect_to_sbs():
    """Connect to the SBS output from Ultrafeeder"""
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((SBS_HOST, SBS_PORT))
            logger.info(f"Connected to SBS feed at {SBS_HOST}:{SBS_PORT}")
            return s
        except socket.error as e:
            logger.error(f"Failed to connect to SBS feed at {SBS_HOST}:{SBS_PORT}: {e}. Retrying in 5 seconds...")
            time.sleep(5)

def create_producer():
    """Create and return a Kafka producer using confluent-kafka"""
    conf = {
        'bootstrap.servers': KAFKA_BROKER,
        'security.protocol': 'SASL_PLAINTEXT',
        'sasl.mechanism': 'PLAIN',
        'sasl.username': KAFKA_USERNAME,
        'sasl.password': KAFKA_PASSWORD,
        'client.id': 'adsb-producer'
    }
    
    try:
        producer = Producer(conf)
        logger.info(f"Connected to Kafka at {KAFKA_BROKER} on topic {KAFKA_TOPIC} as user {KAFKA_USERNAME}")
        return producer
    except Exception as e:
        logger.error(f"Failed to create Kafka producer: {e}")
        raise

def delivery_report(err, msg):
    """Called once for each message produced to indicate delivery result."""
    if err is not None:
        logger.error(f"Message delivery failed: {err}")
    else:
        logger.debug(f"Message delivered to {msg.topic()} [{msg.partition()}] at offset {msg.offset()}")

def send_message(producer, message):
    """Send a message to Kafka with proper error handling"""
    msg_data = {
        'raw_message': message,
        'timestamp': datetime.datetime.now().isoformat()
    }
    
    try:
        # Produce message
        producer.produce(
            KAFKA_TOPIC,
            key=None,
            value=json.dumps(msg_data).encode('utf-8'),
            callback=delivery_report
        )
        # Serve delivery callbacks from previous produce calls
        producer.poll(0)
        return True
    except Exception as e:
        logger.error(f"Failed to send message to Kafka: {e}")
        return False

def shutdown(producer, socket):
    """Gracefully shut down resources"""
    try:
        logger.info("Shutting down producer...")
        if producer:
            # Wait for any outstanding messages to be delivered
            producer.flush()
        if socket:
            socket.close()
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

def main():
    # Check if credentials are available
    if not KAFKA_PASSWORD:
        raise ValueError("Kafka producer password not found in environment variables")
    
    # Make sure topic exists
    ensure_topic_exists()
    
    # Create producer
    producer = create_producer()
    
    # Connect to the SBS feed
    sbs_socket = connect_to_sbs()
    
    # Counters for monitoring
    messages_received = 0
    messages_sent = 0
    last_stats_time = time.time()
    
    # Read and process data
    buffer = ""
    while True:
        try:
            data = sbs_socket.recv(1024).decode('utf-8', errors='replace')
            if not data:
                logger.warning("Connection lost, reconnecting...")
                sbs_socket.close()
                sbs_socket = connect_to_sbs()
                continue
            
            buffer += data
            messages = buffer.split('\n')
            buffer = messages.pop()  # Keep incomplete message in the buffer
            
            for message in messages:
                if message.strip():
                    messages_received += 1
                    if send_message(producer, message):
                        messages_sent += 1
            
            # Print stats every 30 seconds
            current_time = time.time()
            if current_time - last_stats_time > 30:
                logger.info(f"Stats: Received {messages_received} messages, sent {messages_sent} messages")
                last_stats_time = current_time
                
                # Flush messages periodically
                producer.flush()
            
        except Exception as e:
            logger.error(f"Error processing data: {e}")
            time.sleep(1)
            try:
                sbs_socket.close()
            except:
                pass
            sbs_socket = connect_to_sbs()
    
    return producer, sbs_socket

if __name__ == "__main__":
    producer = None
    sbs_socket = None
    try:
        producer, sbs_socket = main()
    except KeyboardInterrupt:
        logger.info("Shutting down due to keyboard interrupt...")
        shutdown(producer, sbs_socket)
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        shutdown(producer, sbs_socket)