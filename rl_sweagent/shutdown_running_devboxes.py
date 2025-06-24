from runloop_api_client import Runloop


def main():
    client = Runloop()

    active_devboxes = client.devboxes.list(status="running")
    for dbx in active_devboxes.devboxes:
        try:
            client.devboxes.shutdown(dbx.id)
        except Exception as e:
            print(f"failed to shutdown dbx.id={dbx.id}: {e}")


if __name__ == "__main__":
    main()
