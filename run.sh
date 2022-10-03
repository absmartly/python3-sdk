pip install .
python setup.py check
pip install pylint
pylint ./sdk
python -m unittest discover test