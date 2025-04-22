import socket
import time
from kafka import KafkaProducer, KafkaAdminClient
from kafka.admin import NewTopic
from kafka.errors import KafkaError, TopicAlreadyExistsError
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
KAFKA_BROKER = os.getenv('KAFKA_BROKER', 'broker:29092')
KAFKA_TOPIC = os.getenv('TOPIC_NAME', 'adsb-raw')

# Load credentials from environment variables
KAFKA_USERNAME = os.getenv('KAFKA_PRODUCER_USERNAME', 'producer')
KAFKA_PASSWORD = os.getenv('KAFKA_PRODUCER_PASSWORD', '')

def ensure_topic_exists():
    """Ensure that the Kafka topic exists"""
    try:
        admin_client = KafkaAdminClient(
            bootstrap_servers=KAFKA_BROKER,
            security_protocol='SASL_PLAINTEXT',
            sasl_mechanism='PLAIN',
            sasl_plain_username=KAFKA_USERNAME,
            sasl_plain_password=KAFKA_PASSWORD,
            api_version=(2, 5, 0)
        )
        
        # Create topic if it doesn't exist
        topic = NewTopic(
            name=KAFKA_TOPIC,
            num_partitions=1,
            replication_factor=1
        )
        
        admin_client.create_topics([topic])
        logger.info(f"Created topic: {KAFKA_TOPIC}")
    except TopicAlreadyExistsError:
        logger.info(f"Topic {KAFKA_TOPIC} already exists")
    except Exception as e:
        logger.error(f"Error creating topic: {e}")
    finally:
        if 'admin_client' in locals():
            admin_client.close()

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
    """Create and return a Kafka producer"""
    try:
        # Initialize Kafka producer with SASL authentication
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BROKER,
            security_protocol='SASL_PLAINTEXT',
            sasl_mechanism='PLAIN',
            sasl_plain_username=KAFKA_USERNAME,
            sasl_plain_password=KAFKA_PASSWORD,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            api_version=(2, 5, 0),  # Compatible with newer Kafka versions
            acks='all',  # Wait for all replicas to acknowledge
            retries=5,   # Retry a few times before giving up
            batch_size=16384,  # Batch size in bytes
            linger_ms=100,  # Wait up to 100ms to batch messages
            buffer_memory=33554432,  # 32MB buffer
        )
        logger.info(f"Connected to Kafka at {KAFKA_BROKER} on topic {KAFKA_TOPIC} as user {KAFKA_USERNAME}")
        return producer
    except Exception as e:
        logger.error(f"Failed to create Kafka producer: {e}")
        raise

def send_message(producer, message):
    """Send a message to Kafka with proper error handling"""
    msg_data = {
        'raw_message': message,
        'timestamp': datetime.datetime.now().isoformat()
    }
    
    try:
        future = producer.send(KAFKA_TOPIC, msg_data)
        # Block for 'synchronous' behavior to check for errors
        record_metadata = future.get(timeout=10)
        logger.debug(f"Message sent to {record_metadata.topic} partition {record_metadata.partition}, offset {record_metadata.offset}")
        return True
    except KafkaError as e:
        logger.error(f"Failed to send message to Kafka: {e}")
        return False

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

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")