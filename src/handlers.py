# Local Imports
from src.utils import format_date_to_iso
from src.database import Database

# External Imports
from fastapi.responses import JSONResponse
from datetime import datetime, timezone

import traceback
import stripe


async def handle_subscription_update(db: Database, stripe_customer_id: str, product_id: str):
    try:
        user_ref = await db.query_user_ref("stripeCustomerId", stripe_customer_id)
        if user_ref is None:
            print(f"User not found. Customer ID: {stripe_customer_id}")
            return JSONResponse(
                content={
                    "message": f"User not found. Customer ID: {stripe_customer_id}"
                },
                status_code=404,
            )

        user_snapshot = await user_ref.get()
        user = user_snapshot.to_dict()

        user_subscriptions = user.get("subscriptions", [])

        # Get the users member subscription
        user_member_subscription = None
        for sub in user_subscriptions:
            if "member" in sub.get("name"): 
                user_member_subscription = sub
                break

        if user_member_subscription is None:
            return JSONResponse(
                content={
                    "message": f"Subscription not found. Product ID: {product_id}",
                    "customer": stripe_customer_id,
                },
                status_code=404,
            )

        override = user_member_subscription.get("override")
        if override == False:
            # Remove the old subscription
            await db.remove_subscriptions(user_ref, [{"id": product_id}])
            print(f"Subscription inactive, removed {product_id} from user")

            return JSONResponse(
                content={
                    "message": f"Subscription inactive, removed {product_id} from user",
                    "customer": stripe_customer_id,
                },
                status_code=200,
            )

        # Get the product name from the product id and then add the new subscription
        product = stripe.Product.retrieve(product_id)
        product_name = product.get("name")

        new_subscription = {
            "id": product_id,
            "name": product_name,
            "override": False,
            "createdAt": format_date_to_iso(datetime.now(timezone.utc)),
        }

        await db.add_subscriptions(user_ref, [new_subscription])

    except Exception as e:
        print(f"An error occured in handle_subscription_update(): {e}")
        print(traceback.format_exc())
        return JSONResponse(
            content={"message": "An error occured in handle_subscription_update()"},
            status_code=500,
        )


async def handle_subscription_deletion(db: Database, stripe_customer_id: str, product_id: str):
    try: 
        user_ref = await db.query_user_ref("stripeCustomerId", stripe_customer_id)
        if user_ref is None:
            print(f"User not found. Customer ID: {stripe_customer_id}")
            return JSONResponse(
                content={
                    "message": f"User not found. Customer ID: {stripe_customer_id}"
                },
                status_code=404,
            )

        user_snapshot = await user_ref.get()
        user = user_snapshot.to_dict()
        user_subscriptions = user.get("subscriptions", [])

        user_subscription = None
        for sub in user_subscriptions:
            if sub.get("id") == product_id:
                user_subscription = sub
                break

        if user_subscription is None:
            return JSONResponse(
                content={
                    "message": f"Subscription not found. Product ID: {product_id}",
                    "customer": stripe_customer_id,
                },
                status_code=404,
            )

        override = user_subscription.get("override")
        if override == False:
            await db.remove_subscriptions(user_ref, [{"id": product_id}])

            print(f"Subscription inactive, removed {product_id} from user")
            return JSONResponse(
                content={
                    "message": f"Subscription inactive, removed {product_id} from user",
                    "customer": stripe_customer_id,
                },
                status_code=200,
            )

        print(f"User subscription not removed because of override set to {override}")
        return JSONResponse(
            content={
                "message": f"User subscription not removed because of override set to {override}"
            },
            status_code=200,
        )

    except Exception as error:
        print(f"An error occurred in handle_subscription_deletion(): {error}")
        print(traceback.format_exc())
        return JSONResponse(
            content={
                "message": "An error occurred while processing the subscription deletion",
                "error": str(error),
            },
            status_code=500,
        )
