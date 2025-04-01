# Local Imports


# External Imports
from google.cloud.firestore_v1.async_client import AsyncClient
from google.cloud.firestore_v1 import AsyncDocumentReference, DocumentReference
from google.oauth2 import service_account
from google.cloud import firestore
from dotenv import load_dotenv

import traceback
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
    _firebase_credentials = None 

    def __init__(self):
        if not Database._initialized:
            # Credentials for service account
            Database._firebase_credentials = service_account.Credentials.from_service_account_info(
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

    async def get_db_client(self) -> AsyncClient:
        return AsyncClient(
            project=Database.FIREBASE_PROJECT_ID,
            credentials=Database._firebase_credentials,
        )

    async def query_user_ref(self, key, value) -> AsyncDocumentReference | None:
        try: 
            db: AsyncClient = await self.get_db_client()
            # Query and get matching documents
            query_ref = db.collection("users").where(key, "==", value)
            results = query_ref.stream()

            # Return the document reference of the first match
            async for doc in results:
                return db.document(doc.reference.path)

        except Exception as error:
            print(f"An error occurred in query_user_ref(): {error}")
            print(traceback.format_exc())

    async def add_subscriptions(
        self, user_ref: AsyncDocumentReference, subscriptions_to_add
    ):
        try:
            # Fetch user data
            user_data = (await user_ref.get()).to_dict()
            current_subscriptions = user_data.get("subscriptions", [])

            current_subscription_ids = {sub['id'] for sub in current_subscriptions}

            # Find subscriptions that are not already in the user's subscriptions
            member_sub = None
            new_subscriptions = []
            for sub in subscriptions_to_add:
                if sub['id'] not in current_subscription_ids:
                    new_subscriptions.append(sub)
                
                if "member" in sub.get("name", ""):
                    member_sub: dict = sub
            
            # Add the subscription name to the authentication field
            # e.g. free, standard, pro, etc.
            if member_sub is not None:
                sub_name: str = member_sub.get("name", "")
                name = sub_name.replace(" - member", "").lower()
                authentication = user_data.get("authentication", {})
                authentication["subscribed"] = name

            # Add only new subscriptions
            if new_subscriptions:
                await user_ref.update(
                    {
                        "authentication": authentication,
                        "subscriptions": firestore.ArrayUnion(new_subscriptions)
                    }
                )

            # Fetch the user data
            subscribed_user = (await user_ref.get()).to_dict()

            # Check if the user was referred by another user
            referred_by = subscribed_user.get("referral", {}).get("referredBy")

            if referred_by:
                db: AsyncClient = await self.get_db_client()
                # Get the referring user
                referring_user_query = db.collection("users").where(
                    "referral.referralCode", "==", referred_by
                )
                referring_results = await referring_user_query.get()

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

        except Exception as error:
            print(f"An error occurred in remove_subscriptions(): {error}")
            print(traceback.format_exc())

    async def remove_subscriptions(
        self, user_ref: AsyncDocumentReference, subscriptions_to_remove
    ):
        try: 
            # Fetch the user's current subscriptions
            user_snapshot = await user_ref.get()
            user_data = user_snapshot.to_dict()

            current_subscriptions = user_data.get("subscriptions", [])
            authentication = user_data.get("authentication", {})    

            # Extract the IDs from the subscriptions to remove
            subscription_ids_to_remove = {sub["id"] for sub in subscriptions_to_remove}

            # Create an array of subscriptions to remove based on IDs
            subscriptions_to_remove_final = [
                sub for sub in current_subscriptions if sub["id"] in subscription_ids_to_remove
            ]

            if subscriptions_to_remove_final:
                authentication.pop("subscribed", None)
                # Remove subscriptions by their ID using ArrayRemove
                await user_ref.update(
                    {
                        "authentication": authentication,
                        "subscriptions": firestore.ArrayRemove(subscriptions_to_remove_final)
                    }
                )

        except Exception as error:
            print(f"An error occurred in remove_subscriptions(): {error}")
            print(traceback.format_exc())
