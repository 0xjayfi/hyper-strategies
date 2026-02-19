.PHONY: dev backend frontend build docker-up docker-down install

dev:
	@echo "Starting backend and frontend..."
	@$(MAKE) backend &
	@$(MAKE) frontend &
	@wait

backend:
	cd $(CURDIR) && python -m backend.run

frontend:
	cd $(CURDIR)/frontend && npm run dev

build:
	cd $(CURDIR)/frontend && npm run build

docker-up:
	docker-compose up --build -d

docker-down:
	docker-compose down

install:
	pip install -e ".[backend]"
	cd frontend && npm install
