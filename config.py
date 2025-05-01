'''
Sourcebot configuration
'''
# Third-party libraries
import yaml

MAIN_CONFIG = "config/main.yml"

# Load config files
with open(MAIN_CONFIG) as file:
    config = yaml.safe_load(file)
