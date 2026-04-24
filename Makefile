SERVICE=tradinglive

logs:
	journalctl -u $(SERVICE) -f

restart:
	sudo systemctl restart $(SERVICE)

stop:
	sudo systemctl stop $(SERVICE)

status:
	sudo systemctl status $(SERVICE)

update:
	git pull && sudo systemctl restart $(SERVICE)
