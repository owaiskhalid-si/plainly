# Caching the catalogue, not the cart

We put a cache in front of the product catalogue last month. This note says what we cached, what we left alone, and what it cost.

## What we cached

The catalogue: product pages, category listings and search results for anonymous visitors. These pages change when someone in the merchandising team edits a product, which happens about forty times a day, and almost never between 10 pm and 7 am. Each page is read thousands of times between edits, so a cache pays for itself quickly.

Pages are stored in Redis with a one-hour expiry. When a product is edited, the admin app deletes that product's page and the category pages it appears on. Search results are not deleted on edit; they simply expire. A stale search result for up to an hour is acceptable, and deleting them precisely would have meant indexing which queries return which products.

## What we did not cache

The cart, the checkout and any page for a signed-in customer. Those pages differ for every visitor, so a shared cache would either serve the wrong person's data or have a hit rate near zero. Signed-in requests skip the cache entirely; the check is a single cookie.

## Results

The p95 response time for product pages went from 910 ms to 120 ms. Database load on a weekday afternoon dropped from about 2,100 queries per second to 380. Redis uses 1.4 GB for the catalogue, which costs us $38 a month.

Two things went wrong. The first week, an edit to a product's price did not clear the category pages, because the delete call listed the product's categories at the time of the delete, not at the time of the last save. We fixed it by storing the category list alongside the cached page. The second problem was our own staging environment, which shares the Redis instance with production; a load test on staging evicted half the production cache. Staging now has its own instance.

## What to do next

Cache the category pages for signed-in customers too, but keyed by customer segment rather than by customer. There are six segments, so the hit rate would still be high. We'll try it in November and measure the same two numbers.
