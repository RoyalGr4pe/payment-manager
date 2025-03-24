from api.database import Database
from api.utils import run_inital_subscription_check, format_date_to_iso

from datetime import datetime, timezone
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from fastapi import FastAPI, Request
from slowapi import Limiter
from dotenv import load_dotenv

import asyncio
import jsonify
import uvicorn
import stripe
import os


load_dotenv()



# Connect to Firebase
db = None

def get_db():
    global db
    if not db:
        db = Database()
    return db


def setup_app():
    # Initialize Limiter
    limiter = Limiter(key_func=get_remote_address)

    app = FastAPI(
        title="Flippify Payment API",
        description="API for handling Stripe events",
        version="1.0.0",
    )

    # Attach the limiter to the FastAPI app
    app.state.limiter = limiter

    # Add exception handler for rate limit exceeded errors
    async def ratelimit_error(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded, please try again later."},
        )


    app.add_exception_handler(RateLimitExceeded, ratelimit_error)

    # Setup CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app

app = setup_app()

stripe.api_key = os.getenv("LIVE_STRIPE_API_KEY")


# ----------------------------------------------------------------- #
# Endpoints which receive event messages from stripe                #
# ----------------------------------------------------------------- #


@app.get("/")
@limiter.limit("1/second")
async def root(request: Request):
    return {"name": "Flippify Payments API", "version": "1.0.0", "status": "running"}


def setup_endpoint(request: Request, secret: str):
    try:
        db = get_db()
    except Exception as error:
        return jsonify({"message": "Error in connecting to database"}), 500

    try:
        event = None
        payload = request.data
        sig_header = request.headers["STRIPE_SIGNATURE"]
    except:
        return jsonify({"message": "Failed header information", "event": None, "payload": str(request.data), "sig_header": str(sig_header)}), 500


    try:
        endpoint_secret = os.getenv(secret)
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as error:
        # Invalid payload
        return jsonify({"message": "Failed to create event, Invalid Payload", "error": str(error)}), 400
    except stripe.error.SignatureVerificationError as error:
        # Invalid signature
        return jsonify({"message": "Failed to create event, Invalid Signature", "error": str(error)}), 400

    except Exception as error:
        return jsonify({"message": "Failed to create event, Exception", "error": str(error)}), 500 

    return event, db



# This endpoint is to manually run the initial role check incase anything isn't working
@app.post("/run-initial-role-check")
def run_initial_role_check(request: Request):
    run_inital_subscription_check()



@app.post("/checkout-complete")
async def checkout_complete(request: Request):
    try:
        event, db = setup_endpoint(request, "LIVE_CHECKOUT_COMPLETE_SECRET")
        if event['type'] == 'checkout.session.completed':
            session_data = event['data']['object']

            stripe_customer_id = session_data["customer"]

            subscription_id = session_data["subscription"]
            subscription = stripe.Subscription.retrieve(subscription_id)

            product_id = subscription["plan"]["product"]
            product = stripe.Product.retrieve(product_id)
            prod_name = product['name']

            data = {
                "name": prod_name,
                "id": product_id,
                "override": False,
                "createdAt": format_date_to_iso(datetime.now(timezone.utc))
            }

            user_ref = await db.query_user_ref("stripeCustomerId", stripe_customer_id)
            db.add_subscriptions(user_ref, [data])

        else:
            return jsonify('Unhandled event type {}'.format(event['type'])), 500

    except Exception as error:
        return jsonify({"message": "Failed to update database for checkout", "error": str(error)}), 500

    return jsonify({"message": "Checkout complete"}), 200



@app.post("/subscription-update")
async def subscription_update(request: Request):
    try:
        event, db = setup_endpoint(request, "LIVE_SUBSCRIPTION_UPDATE_SECRET")
        subscription = event["data"]["object"]
        stripe_customer_id = subscription["customer"]
        plan = subscription["plan"]

        if event['type'] == 'customer.subscription.updated':
            pass
        
        elif event["type"] == "customer.subscription.deleted":
            product_id = plan["product"]
            product = stripe.Product.retrieve(product_id)
            prod_name = product['name']

            user_ref = await db.query_user_ref("stripeCustomerId", stripe_customer_id)
            if (user_ref is None):
                return jsonify({"message": f"User not found. Customer ID: {stripe_customer_id}"}), 404
            
            user_snapshot = await user_ref.get()
            user = user_snapshot.to_dict()
            user_subscriptions = user.get("subscriptions", [])

            user_subscription = None
            for sub in user_subscriptions:
                if sub.get("id") == product_id:
                    user_subscription = sub
                    break
            
            if user_subscription is None:
                return jsonify({"message": f"Subscription not found. Product ID: {product_id}", "customer": stripe_customer_id})

            override = user_subscription.get("override")

            subscription_to_remove = {
                "id": product_id
            }

            if override == False:
                db.remove_subscriptions(user_ref, [subscription_to_remove])
                if sub.get("server_subscription") == True:
                    db.remove_webhook({"stripeCustomerId": stripe_customer_id, "subscription_name": prod_name})
                
                return jsonify({"message": f"Subscription inactive, removed {product_id} from users file", "customer": stripe_customer_id})
            
            return jsonify({"message": f"User role not removed because of override set to {override}"}), 200

        else:
            return jsonify('Unhandled event type {}'.format(event['type']))

    except Exception as error:
        return jsonify({"message": "Failed to update database for subscription update", "error": str(error), "function": "subscription_update"}), 500
    
    return jsonify({"message": "Subscription Updated"}), 200



if __name__ == "__main__":
    asyncio.run(run_inital_subscription_check())
    #uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)