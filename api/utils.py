from .database import Database

from datetime import datetime

import stripe


def format_date_to_iso(date: datetime) -> str:
    """Helper function to format dates to the required ISO 8601 format (e.g., 2024-11-01T17:12:26.000Z)."""
    return date.strftime("%Y-%m-%dT%H:%M:%S.000Z")


async def run_initial_subscription_check():
    print("Running initial subscription check...")
    # Note: 'user' refers to database and 'customer' refers to stripe
    db = Database()

    async for user_doc in db.users_col.stream():
        user_ref = user_doc.reference
        user = user_doc.to_dict()

        stripe_customer_id = user.get("stripeCustomerId")
        if stripe_customer_id is None:
            continue

        # Retrieve all the users subscriptions on stripe
        try:
            stripe_customer_subscriptions = stripe.Subscription.list(customer=stripe_customer_id)["data"]
        except stripe._error.InvalidRequestError:
            # This is because the customer is either in test mode but live mode is running or
            # the customer is in live mode but test mode is running
            continue

        subscriptions_to_add = []
        subscriptions_to_remove = []

        # Add any subscriptions the user now has
        for subscription in stripe_customer_subscriptions:
            print(subscription)
            product_id = subscription["plan"]["product"]
            stripe_product = stripe.Product.retrieve(product_id)

            sub_name = stripe_product['name']

            new_subscription = {
                "name": sub_name,
                "id": product_id,
                "override": False,
                "createdAt": format_date_to_iso(datetime.now())
            }
            subscriptions_to_add.append(new_subscription)          

        stripe_customer_subscription_names = [sub['plan']['nickname'] for sub in stripe_customer_subscriptions]

        # Identify subscriptions to remove
        for subscription in user.get('subscriptions', []):
            if (subscription.get("name") == "admin"):
                subscriptions_to_remove = []
                break

            if (subscription.get('name') not in stripe_customer_subscription_names) and (subscription["override"] == False):
                subscriptions_to_remove.append(subscription)

        if subscriptions_to_add:
            db.add_subscriptions(user_ref, subscriptions_to_add)

        if subscriptions_to_remove:
            db.remove_subscriptions(user_ref, subscriptions_to_remove)
