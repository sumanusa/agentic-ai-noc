from app.graph import build_graph


def main():
    """Application entry point."""

    graph = build_graph()

    print("Agentic AI NOC system initialized.")
    print("Ready to receive incidents.")


if __name__ == "__main__":
    main()
