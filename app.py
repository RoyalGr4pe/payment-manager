from src.utils import run_initial_subscription_check, format_date_to_iso
from src.handlers import handle_subscription_update, handle_subscription_deletion
from src.database import Database

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException
from slowapi import Limiter
from dotenv import load_dotenv
from pprint import pprint

import traceback
import uvicorn
import stripe
import os


load_dotenv()

# Setup stripe api key
stripe.api_key = os.getenv("LIVE_STRIPE_API_KEY")


# Initialize FastAPI app with lifespan event
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup event: run the initial subscription check
    try:
        await run_initial_subscription_check()
        print("Initial subscription check completed successfully.")
    except Exception as error:
        print(f"Failed to run initial subscription check: {error}")

    # Yield control to FastAPI to serve requests
    yield

    # Shutdown event (if needed for cleanup)
    print("Shutting down...")


# Connect to Firebase
db = None


def get_db():
    global db
    if not db:
        db = Database()
    return db

# Initialize Limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Flippify Payment API",
    description="API for handling Stripe events",
    version="1.0.0",
    lifespan=lifespan,
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

# ----------------------------------------------------------------- #
# Endpoints which receive event messages from stripe                #
# ----------------------------------------------------------------- #


@app.get("/")
@limiter.limit("5/second")
async def root(request: Request):
    return {"name": "Flippify Payments API", "version": "1.0.0", "status": "running"}


async def setup_endpoint(request: Request, secret: str):
    try:
        db = get_db()
    except Exception as error:
        print(error)
        return JSONResponse(
            content={"message": "Error in connecting to database"}, status_code=500
        )

    try:
        event = None
        payload = await request.body()
        sig_header = request.headers.get("stripe-signature")
    except Exception as error:
        print("Failed header information", error)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed header information",
                "event": None,
                "payload": str(await request.body()),
                "sig_header": str(request.headers.get("stripe-signature")),
            },
        )

    try:
        endpoint_secret = os.getenv(secret)
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError as error:
        # Invalid payload
        print("Value error", error)
        return JSONResponse(
            content={
                "message": "Failed to create event, Invalid Payload",
                "error": str(error),
            },
            status_code=400,
        )
    except stripe.error.SignatureVerificationError as error:
        print("SignatureVerificationError", error)
        # Invalid signature
        return JSONResponse(
            content={
                "message": "Failed to create event, Invalid Signature",
                "error": str(error),
            },
            status_code=400,
        )
    except Exception as error:
        print("Unknown", error)
        return JSONResponse(
            content={
                "message": "Failed to create event, Exception",
                "error": str(error),
            },
            status_code=500,
        )

    return event, db


@app.post("/checkout-complete")
@limiter.limit("10/second")
async def checkout_complete(request: Request):
    try:
        event, db = await setup_endpoint(request, "LIVE_CHECKOUT_COMPLETE_SECRET")

        if event["type"] == "checkout.session.completed":
            session_data = event["data"]["object"]
            stripe_customer_id = session_data["customer"]
            subscription_id = session_data["subscription"]

            subscription = stripe.Subscription.retrieve(subscription_id)

            product_id = subscription["plan"]["product"]
            product = stripe.Product.retrieve(product_id)
            prod_name = product["name"]

            data = {
                "name": prod_name,
                "id": product_id,
                "override": False,
                "createdAt": format_date_to_iso(datetime.now(timezone.utc)),
            }

            user_ref = await db.query_user_ref("stripeCustomerId", stripe_customer_id)
            await db.add_subscriptions(user_ref, [data])

        else:
            print(f"Unhandled event type {event['type']}")
            return JSONResponse(
                content={"message": f"Unhandled event type {event['type']}"},
                status_code=500,
            )

    except Exception as error:
        print("An error occur in checkout_complete()", error)
        print(traceback.format_exc())
        return JSONResponse(
            content={
                "message": "Failed to update database for checkout",
                "error": str(error),
            },
            status_code=500,
        )

    return JSONResponse(content={"message": "Checkout complete"}, status_code=200)


@app.post("/subscription-update")
@limiter.limit("10/second")
async def subscription_update(request: Request):
    try:
        event, db = await setup_endpoint(request, "LIVE_SUBSCRIPTION_UPDATE_SECRET")
        subscription = event["data"]["object"]
        stripe_customer_id = subscription["customer"]
        plan = subscription["plan"]
        product_id = plan["product"]

        if event["type"] == "customer.subscription.updated":
            # This function handles when the user has upgraded or downgraded their subscription
            return await handle_subscription_update(db, stripe_customer_id, product_id)

        elif event["type"] == "customer.subscription.deleted":
            return await handle_subscription_deletion(db, stripe_customer_id, product_id)

        else:
            print(f"Unhandled event type {event['type']}")
            return JSONResponse(
                content={"message": f"Unhandled event type {event['type']}"},
                status_code=500,
            )

    except Exception as error:
        print(f"An error occur in subscription_update: {error}")
        print(traceback.format_exc())
        return JSONResponse(
            content={
                "message": "Failed to update database for subscription update",
                "error": str(error),
                "function": "subscription_update",
            },
            status_code=500,
        )

    return JSONResponse(content={"message": "Subscription Updated"}, status_code=200)


# if __name__ == "__main__":
# uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
