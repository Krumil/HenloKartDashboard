from db.operations import save_to_database, save_player_commitment_to_database


def handle_event(event):
    if event["event"] == "RaceFinished":
        save_to_database(event["args"])
    elif event["event"] == "PlayerCommitted":
        save_player_commitment_to_database(event["args"])
