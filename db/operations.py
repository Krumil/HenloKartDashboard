import psycopg2
from utils.helpers import wei_to_ether
from config.db import db_name, db_user, db_password, db_host, db_port


def get_participations(commitment_hashes):
    with psycopg2.connect(
        dbname=db_name, user=db_user, password=db_password, host=db_host, port=db_port
    ) as conn:
        with conn.cursor() as cur:
            players = []
            token_ids = []

            for commitment_hash in commitment_hashes:
                query = """
                SELECT player_address, token_id FROM player_commitments WHERE commitment_hash = %s
                """
                cur.execute(query, (psycopg2.Binary(commitment_hash),))
                result = cur.fetchone()

                if result:
                    players.append(result[0])
                    token_ids.append(result[1])
                else:
                    print(f"Commitment hash {commitment_hash} not found in database")

            return players, token_ids


def save_to_database(event_data):
    players, token_ids = get_participations(event_data["commitmentHashes"])
    participations = len(players)

    # Create a mutable dictionary from the event_data
    event_data_dict = dict(event_data)

    # Convert betSize from wei to ether
    event_data_dict["betSize"] = wei_to_ether(event_data_dict["betSize"])

    with psycopg2.connect(
        dbname=db_name, user=db_user, password=db_password, host=db_host, port=db_port
    ) as conn:
        with conn.cursor() as cur:
            query = """
            INSERT INTO race_results (race_id, winner_address, winning_token_id, steps, commitment_hashes, bet_size, participations, participant_players, participant_token_ids)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (race_id) DO NOTHING
            """
            values = (
                event_data_dict["raceId"],
                event_data_dict["winner"],
                event_data_dict["winningTokenId"],
                event_data_dict["steps"],
                [psycopg2.Binary(ch) for ch in event_data_dict["commitmentHashes"]],
                event_data_dict["betSize"],
                participations,
                players,
                token_ids,
            )
            cur.execute(query, values)


def save_player_commitment_to_database(event_data):
    # Create a mutable dictionary from the event_data
    event_data_dict = dict(event_data)

    with psycopg2.connect(
        dbname=db_name, user=db_user, password=db_password, host=db_host, port=db_port
    ) as conn:
        with conn.cursor() as cur:
            query = """
            INSERT INTO player_commitments (commitment_hash, player_address, agent_address, bet_token, token_id, bet_size, deadline, count, rng_seed)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (commitment_hash) DO NOTHING
            """
            values = (
                psycopg2.Binary(event_data_dict["commitmentHash"]),
                event_data_dict["commitment"]["player"],
                event_data_dict["commitment"]["agent"],
                event_data_dict["commitment"]["betToken"],
                event_data_dict["commitment"]["tokenId"],
                event_data_dict["commitment"]["betSize"],
                event_data_dict["commitment"]["deadline"],
                event_data_dict["commitment"]["count"],
                event_data_dict["commitment"]["rngSeed"],
            )
            cur.execute(query, values)
