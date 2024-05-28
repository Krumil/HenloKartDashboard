import asyncio
from web3.exceptions import TimeExhausted
from config.web3 import web3, contract
from events.handlers import handle_event


async def initial_fetch(start_block):
    latest_block = web3.eth.block_number

    # Fetch and process PlayerCommitted events in batches
    await fetch_player_committed_events_in_batches(start_block, latest_block)

    # Fetch and process RaceFinished events in batches
    await fetch_race_finished_events_in_batches(start_block, latest_block)

    return latest_block


async def fetch_player_committed_events_in_batches(
    from_block, to_block, batch_size=1000
):
    current_block = from_block
    while current_block < to_block:
        end_block = min(current_block + batch_size, to_block)
        print(f"Fetching PlayerCommitted events from {current_block} to {end_block}")
        try:
            await fetch_player_committed_events(current_block, end_block)
            current_block = end_block + 1
        except TimeExhausted:
            print(f"Timeout fetching between blocks {current_block} and {end_block}")
        except Exception as e:
            print(f"An error occurred: {e}")


async def fetch_player_committed_events(from_block, to_block):
    try:
        player_committed_filter = contract.events.PlayerCommitted.create_filter(
            fromBlock=from_block, toBlock=to_block
        )

        player_committed_events = player_committed_filter.get_all_entries()
        for event in player_committed_events:
            handle_event(event)
    except Exception as e:
        print(f"Error fetching PlayerCommitted events: {str(e)}")
        raise e


async def fetch_race_finished_events_in_batches(from_block, to_block, batch_size=1000):
    current_block = from_block
    while current_block < to_block:
        end_block = min(current_block + batch_size, to_block)
        print(f"Fetching RaceFinished events from {current_block} to {end_block}")
        try:
            await fetch_race_finished_events(current_block, end_block)
            current_block = end_block + 1
        except TimeExhausted:
            print(f"Timeout fetching between blocks {current_block} and {end_block}")
        except Exception as e:
            print(f"An error occurred: {e}")


async def fetch_race_finished_events(from_block, to_block):
    try:
        race_finished_filter = contract.events.RaceFinished.create_filter(
            fromBlock=from_block, toBlock=to_block
        )

        race_finished_events = race_finished_filter.get_all_entries()
        for event in race_finished_events:
            handle_event(event)
    except Exception as e:
        print(f"Error fetching RaceFinished events: {str(e)}")
        raise e
