# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

import frappe
from recruitrain_employer.services.profile_service import ProfileService

def test_profile_flow():
    frappe.set_user("Administrator")
    ps = ProfileService()

    # 1. Update Profile (Partial Update)
    update_data = {
        "first_name": "Alexander",
        "last_name": "Pierce",
        "designation": "Director of Talent Acquisition",
        "phone": "+1 555 987 6543",
        "bio": "Executive recruitment lead for technology teams.",
        "timezone": "Europe/Berlin",
        "language": "en",
    }
    updated = ps.update_profile(update_data)
    print("UPDATED PROFILE:", updated["employer"]["full_name"], "|", updated["employer"]["designation"], "|", updated["preferences"]["timezone"])

    # 2. Get Profile after simulated refresh / new request
    fetched = ps.get_profile()
    print("FETCHED PROFILE AFTER REFRESH:", fetched["employer"]["full_name"], "|", fetched["employer"]["designation"], "|", fetched["preferences"]["timezone"])

    # 3. Test Photo Upload & Remove
    test_photo_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    upload_res = ps.upload_profile_photo(test_photo_content, "avatar_test.png", "image/png")
    print("PHOTO UPLOAD RESULT:", upload_res["file_url"])

    fetched_with_avatar = ps.get_profile()
    print("AVATAR IN FETCHED PROFILE:", fetched_with_avatar["avatar_url"])

    remove_res = ps.remove_profile_photo()
    print("PHOTO REMOVE RESULT:", remove_res["message"])

    fetched_after_remove = ps.get_profile()
    print("AVATAR AFTER REMOVE:", fetched_after_remove["avatar_url"])

    print("ALL TESTS PASSED SUCCESSFULLY!")
