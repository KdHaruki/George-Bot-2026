"""Visible ambient diagnostics without message text, credentials or DB writes."""
import logging

logger = logging.getLogger('george.ambient')
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] george.ambient: %(message)s'))
    logger.addHandler(handler)
