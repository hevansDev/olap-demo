import socket
import time
from kafka import KafkaProducer
import json
import datetime

# Configure connection to SBS output from Ultrafeeder
SBS_HOST = 'ultrafeeder'  # Use the container name from your docker-compose
SBS_PORT = 30003  # SBS output port

# Configure connection to Kafka
KAFKA_BROKER = 'broker:29092'  # Internal docker network address
KAFKA_TOPIC = 'adsb-data'

def connect_to_sbs():
    """Connect to the SBS output from Ultrafeeder"""
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((SBS_HOST, SBS_PORT))
            print(f"Connected to SBS feed at {SBS_HOST}:{SBS_PORT}")
            return s
        except socket.error:
            print(f"Failed to connect to SBS feed at {SBS_HOST}:{SBS_PORT}. Retrying in 5 seconds...")
            time.sleep(5)

def main():
    # Initialize Kafka producer
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )
    
    print(f"Connecting to Kafka at {KAFKA_BROKER} on topic {KAFKA_TOPIC}")
    
    # Connect to the SBS feed
    sbs_socket = connect_to_sbs()
    
    # Read and process data
    buffer = ""
    while True:
        try:
            data = sbs_socket.recv(1024).decode('utf-8', errors='replace')
            if not data:
                print("Connection lost, reconnecting...")
                sbs_socket.close()
                sbs_socket = connect_to_sbs()
                continue
            
            buffer += data
            messages = buffer.split('\n')
            buffer = messages.pop()  # Keep incomplete message in the buffer
            
            for message in messages:
                if message.strip():
                    # Just send the raw message to Kafka with timestamp
                    msg_data = {
                        'raw_message': message,
                        'timestamp': datetime.datetime.now().isoformat()
                    }
                    producer.send(KAFKA_TOPIC, msg_data)
                    print(f"Sent message to Kafka: {message[:50]}...")
            
            # Flush messages periodically
            producer.flush()
            
        except Exception as e:
            print(f"Error processing data: {e}")
            time.sleep(1)
            try:
                sbs_socket.close()
            except:
                pass
            sbs_socket = connect_to_sbs()

if __name__ == "__main__":
    main()