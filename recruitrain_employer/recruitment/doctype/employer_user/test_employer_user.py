# Copyright (c) 2026, RecruiTrain  and Contributors
# See license.txt

# import frappe
from frappe.tests import IntegrationTestCase


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestEmployerUser(IntegrationTestCase):
	"""Integration tests for EmployerUser login auditing and lifecycle functionality."""

	def test_login_auditing_workflow(self):
		"""Run the full login auditing test suite."""
		from recruitrain_employer.tests.test_login_audit import run_tests
		run_tests()

