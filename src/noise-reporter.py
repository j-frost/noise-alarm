import os
import sys
import platform
import json
import concurrent.futures
import queue
import usb.core
import usb.util
import random
import time

from google.auth import jwt
from google.cloud import pubsub_v1
from datetime import datetime
from pyee.executor import ExecutorEventEmitter


class SoundMeter:
    def __init__(self):
        # https://www.amazon.de/-/en/gp/product/B01M32WX3H
        self.dev = usb.core.find(idVendor=0x64bd, idProduct=0x74e3)

        if self.dev == None:
            print("Sound Meter not found", file=sys.stderr)
            exit()

        if self.dev.is_kernel_driver_active(0):
            self.dev.detach_kernel_driver(0)
        usb.util.claim_interface(self.dev, 0)

        self.eout = self.dev[0][(0, 0)][0]
        self.ein = self.dev[0][(0, 0)][1]

        self.STATE_REQUEST = bytearray([
            0xb3,
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255),
            0, 0, 0, 0
        ])
        self.dev.read(self.ein.bEndpointAddress,
                      self.ein.wMaxPacketSize)  # clear buffer

    def get_spl(self):
        self.dev.write(self.eout.bEndpointAddress, self.STATE_REQUEST)
        time.sleep(0.05)
        buffer = []

        while True:
            buffer += self.dev.read(self.ein.bEndpointAddress,
                                    self.ein.wMaxPacketSize)
            if len(buffer) == 8:
                break

        return (buffer[0]*256 + buffer[1])/10


if __name__ == '__main__':
    service_account_info = json.load(open("service-account-info.json"))
    audience = 'https://pubsub.googleapis.com/google.pubsub.v1.Publisher'
    credentials = jwt.Credentials.from_service_account_info(
        service_account_info, audience=audience
    )
    publisher = pubsub_v1.PublisherClient(credentials=credentials)
    topic_name = 'projects/{project_id}/topics/{topic}'.format(
        project_id='noise-alarm-dev',
        topic='rasppi-soundmeter-measurements',
    )

    with ExecutorEventEmitter() as ee:
        @ee.on('measurement')
        def send_to_pubsub(measurement):
            print(f"Sending {measurement} to {topic_name}")
            result = publisher.publish(
                topic_name, measurement.encode('utf-8')).result()
            print(f"Successfully sent {measurement} with result {result}")

        soundmeter = SoundMeter()
        hostname = platform.node()
        while True:
            db_val = soundmeter.get_spl()
            measurement = json.dumps({
                'device': hostname,
                'timestamp': datetime.now().astimezone().isoformat(),
                'decibel_level': db_val
            })
            print(f"Measured {measurement}")
            ee.emit('measurement', measurement)
