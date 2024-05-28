def serialize_record(record):
    return {
        **record,
        "timestamp": (
            record["timestamp"].isoformat() if record.get("timestamp") else None
        ),
    }


def wei_to_ether(wei_value):
    return wei_value / 10**18
