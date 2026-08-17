import json
import pytest
from app.parser import parse_message


ACARS_DOWNLINK = '{"vdl2":{"app":{"name":"dumpvdl2","ver":"2.7.0"},"station":"adsb-pi","t":{"sec":1786897449,"usec":0},"freq":136975000,"avlc":{"src":{"addr":"4CADF7","type":"Aircraft"},"dst":{"addr":"1099CA","type":"Ground station"},"acars":{"label":"H1","reg":".EIEXS","flight":"EI501","msg_text":"#DFB/WRG POSRPT"}}}}'
NO_ACARS = '{"vdl2":{"app":{"name":"dumpvdl2","ver":"2.7.0"},"station":"adsb-pi","t":{"sec":1786897512,"usec":0},"freq":136725000,"avlc":{"src":{"addr":"406A6E","type":"Aircraft"},"dst":{"addr":"1099CA","type":"Ground station"}}}}'
UPLINK = '{"vdl2":{"app":{"name":"dumpvdl2","ver":"2.7.0"},"station":"adsb-pi","t":{"sec":1786897600,"usec":0},"freq":136875000,"avlc":{"src":{"addr":"1099CA","type":"Ground station"},"dst":{"addr":"4CADF7","type":"Aircraft"},"acars":{"label":"Q0","reg":".EIEXS","flight":"EI501","msg_text":""}}}}'
X25_ACARS = '{"vdl2":{"app":{"name":"dumpvdl2","ver":"2.7.0"},"station":"adsb-pi","t":{"sec":1786897700,"usec":0},"freq":136825000,"avlc":{"src":{"addr":"3C6444","type":"Aircraft"},"dst":{"addr":"1099CA","type":"Ground station"},"x25":{"acars":{"label":"_d","reg":".DAABX","flight":"DLH123","msg_text":"FANS MESSAGE"}}}}}'
NO_TIMESTAMP = '{"vdl2":{"freq":136975000,"station":"adsb-pi","avlc":{}}}'
CPDLC = '{"vdl2":{"app":{"name":"dumpvdl2","ver":"2.7.0"},"station":"adsb-pi","t":{"sec":1786897800,"usec":0},"freq":136875000,"avlc":{"src":{"addr":"4CADF7","type":"Aircraft"},"dst":{"addr":"1099CA","type":"Ground station"},"x25":{"clnp":{"cotp":{"cpdlc":{"atc_downlink_msg":{"msg_elem":[{"msg_text":"WILCO"}]}}}}}}}}'


def test_acars_downlink():
    r = parse_message(ACARS_DOWNLINK)
    assert r is not None
    assert r["source_icao"] == "4CADF7"
    assert r["destination_icao"] == "1099CA"
    assert r["direction"] == "downlink"
    assert r["frequency_hz"] == 136975000
    assert r["station_id"] == "adsb-pi"
    assert r["aircraft_registration"] == "EIEXS"
    assert r["flight_id"] == "EI501"
    assert r["message_type"] == "H1"
    assert r["message_text"] == "#DFB/WRG POSRPT"
    assert r["received_at"] == "2026-08-16T16:24:09.000Z"
    assert r["received_at_epoch_ms"] == 1786897449000
    assert r["raw_json"] == ACARS_DOWNLINK
    assert len(r["message_hash"]) == 64


def test_no_acars_fields_are_none():
    r = parse_message(NO_ACARS)
    assert r is not None
    assert r["message_type"] is None
    assert r["aircraft_registration"] is None
    assert r["flight_id"] is None
    assert r["message_text"] is None


def test_uplink_direction():
    r = parse_message(UPLINK)
    assert r is not None
    assert r["direction"] == "uplink"


def test_uplink_empty_msg_text_is_null():
    # Q0 ACK — empty msg_text should be stored as None, not ""
    r = parse_message(UPLINK)
    assert r is not None
    assert r["message_text"] is None


def test_reg_leading_dot_stripped():
    r = parse_message(ACARS_DOWNLINK)
    assert r is not None
    assert r["aircraft_registration"] == "EIEXS"  # not ".EIEXS"


def test_x25_acars_extraction():
    r = parse_message(X25_ACARS)
    assert r is not None
    assert r["aircraft_registration"] == "DAABX"
    assert r["flight_id"] == "DLH123"
    assert r["message_text"] == "FANS MESSAGE"


def test_cpdlc_extraction():
    r = parse_message(CPDLC)
    assert r is not None
    assert r["message_type"] == "_d"
    assert r["message_text"] == "WILCO"


def test_missing_timestamp_still_returns_record():
    r = parse_message(NO_TIMESTAMP)
    assert r is not None
    assert r["received_at"] is not None  # falls back to ingestion time
    assert r["received_at_epoch_ms"] is None


def test_malformed_json_returns_none():
    assert parse_message("{not valid json}") is None


def test_non_object_json_returns_none():
    assert parse_message("[1,2,3]") is None


def test_empty_line_returns_none():
    assert parse_message("") is None


def test_hash_is_deterministic():
    r1 = parse_message(ACARS_DOWNLINK)
    r2 = parse_message(ACARS_DOWNLINK)
    assert r1["message_hash"] == r2["message_hash"]


def test_different_messages_have_different_hashes():
    r1 = parse_message(ACARS_DOWNLINK)
    r2 = parse_message(NO_ACARS)
    assert r1["message_hash"] != r2["message_hash"]


def test_raw_json_preserved():
    r = parse_message(ACARS_DOWNLINK)
    assert json.loads(r["raw_json"]) == json.loads(ACARS_DOWNLINK)


def test_icao_uppercased():
    lower = '{"vdl2":{"t":{"sec":1786897449,"usec":0},"freq":136975000,"station":"adsb-pi","avlc":{"src":{"addr":"4cadf7","type":"Aircraft"},"dst":{"addr":"1099ca","type":"Ground station"}}}}'
    r = parse_message(lower)
    assert r["source_icao"] == "4CADF7"
    assert r["destination_icao"] == "1099CA"
