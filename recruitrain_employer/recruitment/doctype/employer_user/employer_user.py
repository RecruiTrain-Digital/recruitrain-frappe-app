# Copyright (c) 2026, RecruiTrain  and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class EmployerUser(Document):
	def get_last_login(self) -> dict:
		"""Return login auditing summary for this Employer User."""
		return {
			"user": self.get("user"),
			"last_login_at": self.get("last_login_at") or self.get("last_login"),
			"last_login_ip": self.get("last_login_ip"),
			"last_login_user_agent": self.get("last_login_user_agent"),
			"login_count": self.get("login_count") or 0,
		}


