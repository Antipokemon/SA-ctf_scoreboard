PYTHON ?= python3

.PHONY: test package clean

test:
	$(PYTHON) -m unittest discover -s tests -v
	$(PYTHON) -m py_compile bin/validatectf.py bin/_ctf_common.py bin/getanswer.py bin/gethints.py bin/validateevents.py appserver/controllers/scoreboard_controller.py tools/build_from_upstream.py

package: test
	$(PYTHON) tools/build_from_upstream.py

clean:
	rm -rf dist __pycache__ tests/__pycache__ bin/__pycache__ appserver/controllers/__pycache__ tools/__pycache__
