# Copyright © 2019 Province of British Columbia
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests to ensure names processors function as intended."""
import base64
import json
from unittest import mock
from unittest.mock import patch

import pytest
import requests
from namex.utils import queue_util

from solr_names_updater.names_processors.names import get_nr_ids_to_delete_from_solr
from solr_names_updater.resources import worker  # noqa: I001

from . import MockResponse, create_nr, helper_create_cloud_event  # noqa: I003


@pytest.mark.parametrize(
    ['message_payload', 'names', 'names_state', 'expected_names_to_add_to_solr', 'not_expected_names_to_add_to_solr'],
    [
        (
            helper_create_cloud_event('APPROVED', 'DRAFT'),
            ['TEST NAME 1', 'TEST NAME 2', 'TEST NAME 3'],
            ['APPROVED', 'CONDITION', 'APPROVED'],
            ['TEST NAME 1', 'TEST NAME 2', 'TEST NAME 3'],
            []
        ),
        (
            helper_create_cloud_event('APPROVED', 'DRAFT'),
            ['TEST NAME 1'],
            ['APPROVED'],
            ['TEST NAME 1'],
            []
        ),
        (
            helper_create_cloud_event('CONDITIONAL', 'DRAFT'),
            ['TEST NAME 1'],
            ['APPROVED'],
            ['TEST NAME 1'],
            []
        ),
        (
            helper_create_cloud_event('APPROVED', 'DRAFT'),
            ['TEST NAME 1', 'TEST NAME 2', 'TEST NAME 3'],
            ['APPROVED', 'NOT_EXAMINED', 'REJECTED'],
            ['TEST NAME 1'],
            ['TEST NAME 2', 'TEST NAME 3']
        ),
        (
            helper_create_cloud_event('CANCELLED', 'DRAFT'),
            ['TEST NAME 1'],
            ['APPROVED'],
            [],
            []
        ),
        (
            helper_create_cloud_event('EXPIRED', 'DRAFT'),
            ['TEST NAME 1'],
            ['APPROVED'],
            [],
            []
        ),
    ]
)
def test_should_add_names_to_solr(
        client,
        app,
        db,
        session,
        message_payload,
        names: list,
        names_state: list,
        expected_names_to_add_to_solr: list,
        not_expected_names_to_add_to_solr: list):
    """Assert that names are added to solr."""

    queue_util.send_name_request_state_msg = mock.Mock(return_value="True")
    data_json = json.loads(base64.b64decode(message_payload['message']['data']).decode('utf-8'))
    nr_num = data_json['data']['request']['nrNum']
    nr_new_state = data_json['data']['request']['newState']
    create_nr(nr_num, nr_new_state, names, names_state)
    # mock_msg = create_queue_mock_message(message_payload)
    mock_response = MockResponse({}, 200)

    # mock post method to solr feeder api
    with patch.object(requests, 'post', return_value=mock_response) as mock_solr_feeder_api_post:
        # mock process_names_delete to do nothing in order to isolate testing relevant to this test
        with patch.object(worker, 'process_names_delete', return_value=True):
            # mock process_possible_conflicts_add to do nothing in order to isolate testing relevant to this test
            with patch.object(worker, 'process_possible_conflicts_add', return_value=True):
                # mock process_possible_conflicts_delete to do nothing in order to isolate testing relevant to this test
                with patch.object(worker, 'process_possible_conflicts_delete', return_value=True):
                    rv = client.post("/", json=message_payload)

                    if len(expected_names_to_add_to_solr) > 0:
                        assert mock_solr_feeder_api_post.called == True
                        assert 'api/v1/feeds' in mock_solr_feeder_api_post.call_args[0][0]

                        post_json = mock_solr_feeder_api_post.call_args[1]['json']
                        assert post_json['solr_core']
                        assert post_json['solr_core'] == 'names'

                        request_json = post_json['request']

                        for index, expect_name in enumerate(expected_names_to_add_to_solr):
                            assert expect_name in request_json

                        for index, not_expect_name in enumerate(not_expected_names_to_add_to_solr):
                            assert not_expect_name not in request_json
                    else:
                        assert mock_solr_feeder_api_post.called == False


@pytest.mark.parametrize(
    ['state_change_type', 'message_payload', 'new_nr_state', 'previous_nr_state', 'names', 'name_states'],
    [
        (
            'request',
            helper_create_cloud_event('CANCELLED', 'APPROVED'),
            'CANCELLED', 'APPROVED',
            ['TEST NAME 1', 'TEST NAME 2', 'TEST NAME 3'],
            ['APPROVED', 'CONDITION', 'REJECTED']
        ),
        (
            'request',
            helper_create_cloud_event('RESET', 'APPROVED'),
            'HOLD', 'APPROVED',
            ['TEST NAME 1', 'TEST NAME 2', 'TEST NAME 3'],
            ['APPROVED', 'CONDITION', 'REJECTED']
        ),
        (
            'request',
            helper_create_cloud_event('RESET', 'APPROVED'),
            'INPROGRESS', 'APPROVED',
            ['TEST NAME 1', 'TEST NAME 2', 'TEST NAME 3'],
            ['APPROVED', 'CONDITION', 'REJECTED']
        ),
        (
            'request',
            helper_create_cloud_event('CONSUMED', 'APPROVED'),
            'CONSUMED', 'APPROVED',
            ['TEST NAME 1', 'TEST NAME 2', 'TEST NAME 3'],
            ['APPROVED', 'CONDITION', 'REJECTED']
        ),

    ]
)
def test_should_delete_names_from_solr(
        client,
        app,
        db,
        session,
        state_change_type,
        message_payload,
        new_nr_state,
        previous_nr_state,
        names: list,
        name_states: list):
    """Assert that names are deleted from Solr."""

    queue_util.send_name_request_state_msg = mock.Mock(return_value="True")
    queue_util.send_name_state_msg = mock.Mock(return_value="True")
    data_json = json.loads(base64.b64decode(message_payload['message']['data']).decode('utf-8'))
    nr_num = data_json['data'][state_change_type]['nrNum']
    mock_nr = create_nr(nr_num, new_nr_state, names, name_states)
    nr_ids_to_delete_from_solr = get_nr_ids_to_delete_from_solr(mock_nr)
    mock_response = MockResponse({}, 200)

    # mock post method to solr feeder api
    with patch.object(requests, 'post', return_value=mock_response) as mock_solr_feeder_api_post:
        # mock process_possible_conflicts_delete to do nothing in order to isolate testing relevant to this test
        with patch.object(worker, 'process_possible_conflicts_delete', return_value=True):
            rv = client.post("/", json=message_payload)

            assert mock_solr_feeder_api_post.called == True
            assert 'api/v1/feeds' in mock_solr_feeder_api_post.call_args[0][0]

            post_json = mock_solr_feeder_api_post.call_args[1]['json']
            assert post_json['solr_core']
            assert post_json['solr_core'] == 'names'

            request_json = post_json['request']

            assert 'delete' in request_json
            assert len(nr_ids_to_delete_from_solr) > 0
            request_json = post_json['request']
            for nr_id in nr_ids_to_delete_from_solr:
                assert nr_id in request_json
