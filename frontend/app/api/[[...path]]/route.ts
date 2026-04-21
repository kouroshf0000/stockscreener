import { NextRequest, NextResponse } from "next/server";

const BACKEND = "https://stockscreener-3vlt.onrender.com";

async function proxy(req: NextRequest): Promise<NextResponse> {
  const url = new URL(req.url);
  const target = `${BACKEND}${url.pathname}${url.search}`;

  const headers = new Headers(req.headers);
  headers.delete("host");

  const upstream = await fetch(target, {
    method: req.method,
    headers,
    body: ["GET", "HEAD"].includes(req.method) ? undefined : req.body,
    // @ts-expect-error — Node fetch duplex needed for streaming bodies
    duplex: "half",
  });

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: upstream.headers,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
