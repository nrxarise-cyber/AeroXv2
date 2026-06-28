import aiohttp
import json

async def get_bin_info(card_number):
    try:
        bin_number = card_number[:6]

        timeout = aiohttp.ClientTimeout(total=10)

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(
                f"https://bins.antipublic.cc/bins/{bin_number}"
            ) as response:

                if response.status != 200:
                    return (
                        "-",
                        "-",
                        "-",
                        "-",
                        "-",
                        ""
                    )

                text = await response.text()

                try:
                    data = json.loads(text)

                    return (
                        data.get("brand", "-"),
                        data.get("type", "-"),
                        data.get("level", "-"),
                        data.get("bank", "-"),
                        data.get("country_name", "-"),
                        data.get("country_flag", "")
                    )

                except json.JSONDecodeError:
                    return (
                        "-",
                        "-",
                        "-",
                        "-",
                        "-",
                        ""
                    )

    except Exception:
        return (
            "-",
            "-",
            "-",
            "-",
            "-",
            ""
        )