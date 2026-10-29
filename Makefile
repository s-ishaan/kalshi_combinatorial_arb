.PHONY: help test replay live benchmark demo

help:
	@echo "Available commands:"
	@echo "  make demo       - Run tests, historical replay, benchmark, and live scanner"
	@echo "  make test       - Run all 15 unit tests"
	@echo "  make replay     - Run tick-by-tick historical Kalshi order book replay"
	@echo "  make benchmark  - Run synthetic FOMC rate decision & capacity curves"
	@echo "  make live       - Scan live public Kalshi markets in real-time"

test:
	python3 -m unittest discover -s tests -p "test_*.py" -v

replay:
	python3 main.py --mode replay

benchmark:
	python3 main.py --mode benchmark

live:
	python3 main.py --mode live

demo:
	./run.sh
