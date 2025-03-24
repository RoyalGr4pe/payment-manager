# Local Imports


# External Imports
from google.cloud.firestore_v1.async_client import AsyncClient
from google.cloud.firestore_v1 import AsyncDocumentReference
from google.oauth2 import service_account
from google.cloud import firestore
from dotenv import load_dotenv


import os

load_dotenv()


class Database():
    # Class-level attributes for environment variables
    FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
    FIREBASE_PRIVATE_KEY_ID = os.getenv("FIREBASE_PRIVATE_KEY_ID")
    FIREBASE_PRIVATE_KEY = os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n")
    FIREBASE_CLIENT_EMAIL = os.getenv("FIREBASE_CLIENT_EMAIL")
    FIREBASE_CLIENT_ID = os.getenv("FIREBASE_CLIENT_ID")
    FIREBASE_CLIENT_X509_CERT_URL = os.getenv("FIREBASE_CLIENT_X509_CERT_URL")
    FIREBASE_PROJECT_URL = os.getenv("FIREBASE_PROJECT_URL")

    # A flag to track initialization
    _initialized = False

    def __init__(self):
        if not Database._initialized:
            # Credentials for service account
            firebase_credentials = service_account.Credentials.from_service_account_info(
                {
                    "type": "service_account",
                    "project_id": Database.FIREBASE_PROJECT_ID,
                    "private_key_id": Database.FIREBASE_PRIVATE_KEY_ID,
                    "private_key": Database.FIREBASE_PRIVATE_KEY,
                    "client_email": Database.FIREBASE_CLIENT_EMAIL,
                    "client_id": Database.FIREBASE_CLIENT_ID,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "client_x509_cert_url": Database.FIREBASE_CLIENT_X509_CERT_URL,
                    "universe_domain": "googleapis.com",
                }
            )

            # Mark as initialized
            Database._initialized = True

        # Firestore client
        self.db = AsyncClient(
            project=Database.FIREBASE_PROJECT_ID, credentials=firebase_credentials
        )

        self.users_col = self.db.collection("users")

    def query_user_ref_by_id(self, uid: str) -> AsyncDocumentReference:
        """
        Retrieve a user reference by uid.
        """
        return self.db.collection("users").document(uid)
    
    async def query_user_ref(self, key, value) -> AsyncDocumentReference | None:
        # Query and get matching documents
        query_ref = self.db.collection("users").where(key, "==", value)
        results = await query_ref.stream()

        # Return the document reference of the first match
        async for doc in results:
            return doc.reference
        
        # Return None if no match found
        return None
    
    async def add_subscriptions(self, user_ref: AsyncDocumentReference, subscriptions_to_add):
        # Add subscriptions using array_union
        await user_ref.update({
            "subscriptions": firestore.ArrayUnion(subscriptions_to_add)
        })

        # Fetch the user data
        subscribed_user = (await user_ref.get()).to_dict()

        # Check if the user was referred by another user
        referred_by = subscribed_user.get("referral", {}).get("referredBy")

        if referred_by:
            # Get the referring user
            referring_query = self.users_col.where("referral.referralCode", "==", referred_by)
            referring_results = await referring_query.get()

            for ref_doc in referring_results:
                referring_user_ref: AsyncDocumentReference = ref_doc.reference
                referring_user_data = ref_doc.to_dict()

                # Get the subscribed user's referral code
                subscribed_user_id = subscribed_user.get("id")

                # Check if referral code is already in valid_referrals
                if (
                    subscribed_user_id
                    and subscribed_user_id
                    not in referring_user_data.get("referral", {}).get("validReferrals", [])
                ):
                    # Add to valid_referrals using array_union
                    await referring_user_ref.update({
                        "referral.validReferrals": firestore.ArrayUnion([subscribed_user_id])
                    })

    async def remove_subscriptions(self, user_ref: AsyncDocumentReference, subscriptions_to_remove):
        # Remove subscriptions using array_remove
        await user_ref.update({
            "subscriptions": firestore.ArrayRemove(subscriptions_to_remove)
        })