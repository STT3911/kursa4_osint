from console_utils import configure_console_output
from nlp_search_engine import NLPSearchEngine


def main() -> int:
    configure_console_output()
    engine = NLPSearchEngine()
    print("AI search is ready. Type 'exit' to stop.")

    while True:
        query = input("\nquery: ").strip()
        if query.lower() == "exit":
            break
        if not query:
            continue

        results = engine.search(query, top_k=5)
        if not results:
            print("No matches found.")
            continue

        print("\n--- SEARCH RESULTS ---")
        for item in results:
            username = f"@{item['username']}" if item["username"] else "[hidden]"
            print(f"score: {item['score']:.2f}")
            print(f"{item['first_name']} ({username}) | groups: {item['group_name']}")
            print(f"bio: {item['bio']}")
            if item["site_list"]:
                print(f"sites: {item['site_list']}")
            print("-" * 30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
