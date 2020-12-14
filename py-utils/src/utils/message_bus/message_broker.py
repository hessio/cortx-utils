#!/usr/bin/env python3

# CORTX-Py-Utils: CORTX Python common library.
# Copyright (c) 2020 Seagate Technology LLC and/or its Affiliates
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
# For any questions about this software or licensing,
# please email opensource@seagate.com or cortx-questions@seagate.com.

import sys
import inspect
from collections import namedtuple
from confluent_kafka import Producer, Consumer
from confluent_kafka.admin import AdminClient
from cortx.utils.message_bus.error import MessageBusError
from cortx.utils.schema import Conf

ConsumerRecord = namedtuple("ConsumerRecord",
                            ["message_type", "message", "partition", "offset", "key"])


class MessageBrokerFactory:
    """
    A layer to choose the type of Message Brokers.
    This module helps us to read Broker specific configurations
    and generate Broker specific administrators.
    """

    _brokers = {}

    def __init__(self, message_broker):
        try:
            brokers = inspect.getmembers(sys.modules[__name__], inspect.isclass)
            for name, cls in brokers:
                if name != 'MessageBroker' and name.endswith("Broker"):
                    if message_broker == cls.name:
                        self.adapter = cls(Conf)
        except Exception as e:
            raise MessageBusError(f"Invalid Broker. {e}")


class MessageBroker:
    """ A common interface of Message Brokers"""

    def __init__(self):
        pass

    def send(self, producer, message):
        pass

    def receive(self):
        pass

    def create(self, role):
        pass


class KafkaMessageBroker(MessageBroker):
    """
    Kafka Server based message broker implementation
    """

    name = 'kafka'

    def __init__(self, config):
        """
        Initialize Kafka based Administrator based on provided Configurations
        """
        servers = ','.join([str(server) for server in config.get('global', 'message_broker')['servers']])
        self.config = {'bootstrap.servers': servers}
        self.message_type = None
        self.producer = None
        self.consumer = None
        self.admin = AdminClient(self.config)

    def __call__(self, client, **client_config):
        """
        Initialize Kafka based Producer/Consumer based on provided Configurations
        """
        try:
            self.message_type = client_config['message_type']
            if client_config['client_id']:
                self.config['client.id'] = client_config['client_id']

            if client == 'PRODUCER':
                self.producer = Producer(**self.config)
            elif client == 'CONSUMER':
                self.config['enable.auto.commit'] = False
                if client_config['offset']:
                    self.config['auto.offset.reset'] = client_config['offset']
                if client_config['consumer_group']:
                    self.config['group.id'] = client_config['consumer_group']
                self.consumer = Consumer(**self.config)
                self.consumer.subscribe(self.message_type)
            else:
                assert client == 'PRODUCER' or client == 'CONSUMER'

        except Exception as e:
            raise MessageBusError(f"Invalid Kafka {client} configurations. {e}")

    def send(self, messages):
        """
        Sends list of messages to Kafka cluster(s)
        """
        for each_message in messages:
            self.producer.produce(self.message_type, bytes(each_message, 'utf-8'))
        self.producer.flush()

    def receive(self):
        """
        Receives list of messages to Kafka cluster(s)
        """
        msg_list = self.receive_subscribed(self.consumer)
        return msg_list

    def receive_subscribed(self, consumer):
        """
        Poll on consumer messages
        """
        try:
            while True:
                msg = consumer.poll(timeout=0.5)
                if msg is None:
                    continue
                if msg.error():
                    raise MessageBusError(msg.error())
                else:
                    sys.stderr.write('%% %s [%d] at offset %d with key %s:\n' %
                                     (msg.topic(), msg.partition(), msg.offset(),
                                      str(msg.key())))
                    yield ConsumerRecord(msg.topic(), msg.value(), msg.partition(), msg.offset(), str(msg.key()))

        except KeyboardInterrupt:
            sys.stderr.write('%% Aborted by user\n')
