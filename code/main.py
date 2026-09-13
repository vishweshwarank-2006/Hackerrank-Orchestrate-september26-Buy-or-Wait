import pandas as pd
from pathlib import Path
import re
import pytesseract
from PIL import Image
BASE = Path(__file__).resolve().parent.parent / "dataset"
def load_data():
    return {
        "profiles": pd.read_csv(BASE / "financial_profiles.csv"),
        "events": pd.read_csv(BASE / "financial_events.csv"),
        "requests": pd.read_csv(BASE / "requests.csv"),
        "options": pd.read_csv(BASE / "request_payment_options.csv"),
        "messages": pd.read_csv(BASE / "messages.csv"),
        "images": pd.read_csv(BASE / "images.csv"),
        "rates": pd.read_csv(BASE / "exchange_rates.csv"),
    }
def prepare_events(events):
    events = events.copy()
    events["event_date"] = (
        pd.to_datetime(events["event_date"], errors="coerce")
        .dt.normalize()
    )
    events["settlement_date"] = (
        pd.to_datetime(events["settlement_date"], errors="coerce")
        .dt.normalize()
    )
    events["amount"] = pd.to_numeric(
        events["amount"],
        errors="coerce"
    )
    for column in [
        "event_type",
        "description",
        "category",
        "direction",
        "status",
        "flexibility",
        "currency",
        "linked_event_id",
    ]:
        if column in events.columns:
            events[column] = (
                events[column]
                .fillna("")
                .astype(str)
                .str.strip()
            )
    return events
def extract_amount_from_image(image_path):
    try:
        image = Image.open(image_path)
        text = pytesseract.image_to_string(
            image
        )
        text = str(text).replace(",", "")
        keyword_patterns = [
            r"(?i)(?:total|amount|paid|price|due|net|payment)"
            r"\s*[:\-]?\s*(?:INR|IDR|USD|EUR|ZAR|\$|₹|€|R)"
            r"\s*([0-9]+(?:\.[0-9]+)?)",
            r"(?i)(?:INR|IDR|USD|EUR|ZAR|\$|₹|€|R)"
            r"\s*([0-9]+(?:\.[0-9]+)?)"
        ]
        for pattern in keyword_patterns:
            match = re.search(pattern, text)
            if match:
                value = float(match.group(1))
                if value > 0:
                    return value
        numbers = re.findall(
            r"\b[0-9]+(?:\.[0-9]+)?\b",
            text
        )
        candidates = []
        for value in numbers:
            try:
                number = float(value)
                if number >= 1:
                    candidates.append(number)
            except ValueError:
                continue
        if candidates:
            return max(candidates)
    except Exception:
        return None
    return None
def recover_missing_event_amounts(
    events,
    images
):
    events = events.copy()
    images = images.copy()
    if "event_id" not in events.columns:
        raise ValueError(
            "financial_events.csv must contain event_id"
        )
    required_image_columns = {
        "image_id",
        "related_event_id"
    }
    if not required_image_columns.issubset(
        set(images.columns)
    ):
        raise ValueError(
            "images.csv must contain image_id "
            "and related_event_id"
        )
    image_links = images[
        ["image_id", "related_event_id"]
    ].copy()
    image_links["related_event_id"] = (
        image_links["related_event_id"]
        .astype(str)
        .str.strip()
    )
    image_links["image_id"] = (
        image_links["image_id"]
        .astype(str)
        .str.strip()
    )
    image_map = dict(
        zip(
            image_links["related_event_id"],
            image_links["image_id"]
        )
    )
    media_dir = BASE / "media" / "images"
    recovered_count = 0
    for index in events.index:
        if pd.notna(events.at[index, "amount"]):
            continue
        event_id = str(
            events.at[index, "event_id"]
        ).strip()
        image_id = image_map.get(event_id)
        if not image_id:
            continue
        image_path = (
            media_dir / f"{image_id}.png"
        )
        if not image_path.exists():
            continue
        amount = extract_amount_from_image(
            image_path
        )
        if amount is not None:
            events.at[index, "amount"] = amount
            recovered_count += 1
    print(
        f"IMAGE AMOUNTS RECOVERED: {recovered_count}"
    )
    return events
def prepare_messages(messages):
    messages = messages.copy()
    messages["sent_at"] = pd.to_datetime(
        messages["sent_at"],
        errors="coerce",
        utc=True
    ).dt.tz_localize(None).dt.normalize()
    for column in [
        "message_id",
        "user_id",
        "request_id",
        "related_event_id",
        "source_type",
        "message_text"
    ]:
        if column in messages.columns:
            messages[column] = (
                messages[column]
                .fillna("")
                .astype(str)
                .str.strip()
            )
    return messages
def apply_message_event_updates(events, messages):
    events = events.copy()
    if messages.empty:
        return events
    linked_messages = messages[
        messages["related_event_id"].astype(str).str.strip() != ""
    ].copy()
    for _, message in linked_messages.iterrows():
        event_id = str(
            message["related_event_id"]
        ).strip()
        match = events[
            events["event_id"].astype(str).str.strip()
            == event_id
        ]
        if match.empty:
            continue
        index = match.index[0]
        text = str(
            message["message_text"]
        ).lower().strip()
        direction = str(
            events.at[index, "direction"]
        ).lower().strip()
        pending_credit = any(
            phrase in text
            for phrase in [
                "refund has been initiated but has not reached",
                "refund is still processing",
                "foreign-currency refund is still processing",
                "pengembalian dana sudah diproses, tetapi belum masuk",
                "pengembalian dana masih",
                "payment has not been credited",
                "pembayaran tersebut belum masuk",
                "still in payment processing",
                "still pending"
            ]
        )
        if pending_credit and direction == "credit":
            events.at[index, "status"] = "pending"
        completed_credit = any(
            phrase in text
            for phrase in [
                "proceeds have reached your account",
                "payment was received",
                "have settled in the cash account",
                "sale order is complete",
                "hasil penjualan investasi anda sudah masuk",
                "proceeds from your investment sale have settled",
                "pembayaran sudah diterima"
            ]
        )
        if completed_credit and direction == "credit":
            events.at[index, "status"] = "settled"
        failed_debit = any(
            phrase in text
            for phrase in [
                "previous debit attempt failed",
                "the previous debit attempt failed",
                "debit attempt failed",
                "debit ... gagal",
                "upaya debit sebelumnya gagal"
            ]
        )
        if failed_debit and direction == "debit":
            events.at[index, "status"] = "failed"
        non_cash_investment = any(
            phrase in text
            for phrase in [
                "no units have been sold and no cash proceeds",
                "not sold and no cash proceeds",
                "tidak ada transaksi tunai",
                "investasi tersebut belum dijual"
            ]
        )
        if non_cash_investment:
            events.at[index, "status"] = "unrealized"
    return events
def prepare_exchange_rates(rates):
    rates = rates.copy()
    date_column = next(
        (
            column for column in rates.columns
            if column.lower() in {
                "date",
                "rate_date",
                "effective_date"
            }
        ),
        None
    )
    from_column = next(
        (
            column for column in rates.columns
            if column.lower() in {
                "from_currency",
                "source_currency",
                "base_currency",
                "from"
            }
        ),
        None
    )
    to_column = next(
        (
            column for column in rates.columns
            if column.lower() in {
                "to_currency",
                "target_currency",
                "quote_currency",
                "to"
            }
        ),
        None
    )
    rate_column = next(
        (
            column for column in rates.columns
            if column.lower() in {
                "rate",
                "exchange_rate",
                "conversion_rate"
            }
        ),
        None
    )
    if not all(
        [date_column, from_column, to_column, rate_column]
    ):
        raise ValueError(
            "Could not identify exchange-rate columns. "
            f"Found columns: {list(rates.columns)}"
        )
    rates["rate_date"] = pd.to_datetime(
        rates[date_column],
        errors="coerce"
    ).dt.normalize()
    rates["from_currency_clean"] = (
        rates[from_column]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )
    rates["to_currency_clean"] = (
        rates[to_column]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )
    rates["rate_value"] = pd.to_numeric(
        rates[rate_column],
        errors="coerce"
    )
    return rates[
        [
            "rate_date",
            "from_currency_clean",
            "to_currency_clean",
            "rate_value"
        ]
    ].dropna(subset=["rate_date", "rate_value"])
def get_exchange_rate(
    rates,
    from_currency,
    to_currency,
    event_date
):
    from_currency = str(
        from_currency
    ).strip().upper()
    to_currency = str(
        to_currency
    ).strip().upper()
    event_date = pd.Timestamp(
        event_date
    ).normalize()
    if from_currency == to_currency:
        return 1.0
    direct = rates[
        (rates["from_currency_clean"] == from_currency)
        & (rates["to_currency_clean"] == to_currency)
        & (rates["rate_date"] <= event_date)
    ].sort_values("rate_date")
    if not direct.empty:
        return float(direct.iloc[-1]["rate_value"])
    inverse = rates[
        (rates["from_currency_clean"] == to_currency)
        & (rates["to_currency_clean"] == from_currency)
        & (rates["rate_date"] <= event_date)
    ].sort_values("rate_date")
    if not inverse.empty:
        inverse_rate = float(
            inverse.iloc[-1]["rate_value"]
        )
        if inverse_rate != 0:
            return 1.0 / inverse_rate
    return None
def convert_events_to_home_currency(
    events,
    profiles,
    rates
):
    events = events.copy()
    rates = prepare_exchange_rates(rates)
    profile_currency = profiles[
        ["user_id", "home_currency"]
    ].copy()
    profile_currency["user_id"] = (
        profile_currency["user_id"]
        .astype(str)
    )
    profile_currency["home_currency"] = (
        profile_currency["home_currency"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )
    events["user_id"] = (
        events["user_id"]
        .astype(str)
    )
    events = events.merge(
        profile_currency,
        on="user_id",
        how="left"
    )
    converted_amounts = []
    for _, event in events.iterrows():
        amount = event["amount"]
        if pd.isna(amount):
            converted_amounts.append(amount)
            continue
        source_currency = str(
            event.get("currency", "")
        ).strip().upper()
        home_currency = str(
            event.get("home_currency", "")
        ).strip().upper()
        event_date = event["settlement_date"]
        if (
            not source_currency
            or source_currency == "NAN"
            or not home_currency
            or pd.isna(event_date)
        ):
            converted_amounts.append(float(amount))
            continue
        rate = get_exchange_rate(
            rates,
            source_currency,
            home_currency,
            event_date
        )
        if rate is None:
            raise ValueError(
                "Missing exchange rate: "
                f"{source_currency} -> "
                f"{home_currency} on "
                f"{event_date.strftime('%Y-%m-%d')}"
            )
        converted_amounts.append(
            float(amount) * rate
        )
    events["amount"] = converted_amounts
    events["currency"] = (
        events["home_currency"]
    )
    events = events.drop(
        columns=["home_currency"],
        errors="ignore"
    )
    return events
def prepare_requests(requests):
    requests = requests.copy()
    requests["request_date"] = (
        pd.to_datetime(requests["request_date"], errors="coerce")
        .dt.normalize()
    )
    requests["desired_completion_date"] = (
        pd.to_datetime(
            requests["desired_completion_date"],
            errors="coerce"
        )
        .dt.normalize()
    )
    requests["requested_amount"] = pd.to_numeric(
        requests["requested_amount"],
        errors="coerce"
    )
    return requests
def get_profile(data, user_id):
    rows = data["profiles"][
        data["profiles"]["user_id"].astype(str) == str(user_id)
    ]
    if rows.empty:
        raise ValueError(f"Profile not found: {user_id}")
    return rows.iloc[0]
def get_user_events(data, user_id):
    events = data["events"]
    return events[
        events["user_id"].astype(str) == str(user_id)
    ].copy()
def event_is_usable(event):
    status = str(event["status"]).lower().strip()
    direction = str(event["direction"]).lower().strip()
    if status in {
        "failed",
        "cancelled",
        "unrealized"
    }:
        return False
    if status == "pending" and direction == "credit":
        return False
    if pd.isna(event["amount"]):
        return False
    if pd.isna(event["settlement_date"]):
        return False
    return True
def detect_recurring_events(history):
    if history.empty:
        return []
    history = history.copy()
    history = history[
        history["amount"].notna()
        & history["settlement_date"].notna()
    ].copy()
    history = history[
        history["status"].isin(
            {"settled", "scheduled"}
        )
    ].copy()
    excluded_types = {
        "refund",
        "investment",
        "transfer",
        "salary",
    }
    history = history[
        ~history["event_type"]
        .str.lower()
        .isin(excluded_types)
    ].copy()
    history = history[
        history["category"].str.lower() != "salary"
    ].copy()
    if history.empty:
        return []
    recurring = []
    group_columns = [
        "event_type",
        "description",
        "category",
        "direction",
    ]
    for _, group in history.groupby(
        group_columns,
        dropna=False
    ):
        group = group.sort_values(
            "settlement_date"
        )
        if len(group) < 3:
            continue
        dates = (
            group["settlement_date"]
            .drop_duplicates()
            .sort_values()
        )
        gaps = dates.diff().dt.days.dropna()
        if len(gaps) < 2:
            continue
        median_gap = float(gaps.median())
        if median_gap < 5 or median_gap > 60:
            continue
        tolerance = max(
            3,
            median_gap * 0.30
        )
        consistent = (
            (gaps - median_gap).abs()
            <= tolerance
        ).mean()
        if consistent < 0.60:
            continue
        recent = group.tail(
            min(3, len(group))
        )
        recurring.append({
            "scope": "description",
            "description": str(
                group["description"].iloc[-1]
            ),
            "category": str(
                group["category"].iloc[-1]
            ).lower(),
            "direction": str(
                group["direction"].iloc[-1]
            ).lower(),
            "flexibility": str(
                group["flexibility"].iloc[-1]
            ).lower(),
            "median_gap": int(
                round(median_gap)
            ),
            "amount": float(
                recent["amount"].median()
            ),
            "last_date": dates.iloc[-1].normalize(),
        })
    description_rules = recurring.copy()
    category_groups = history.groupby(
        ["category", "direction"],
        dropna=False
    )
    for (category, direction), group in category_groups:
        category = str(category).lower()
        direction = str(direction).lower()
        essential_categories = {
            "groceries",
        }
        if category not in essential_categories:
            continue
        if category in {
            "",
            "nan",
            "salary",
        }:
            continue
        if direction != "debit":
            continue
        group = group.sort_values(
            "settlement_date"
        )
        if len(group) < 4:
            continue
        if group["description"].astype(str).nunique() < 2:
            continue
        daily = (
            group.groupby("settlement_date")["amount"]
            .sum()
            .sort_index()
        )
        dates = daily.index.sort_values()
        gaps = dates.to_series().diff().dt.days.dropna()
        if len(gaps) < 3:
            continue
        median_gap = float(
            gaps.median()
        )
        if median_gap < 5 or median_gap > 60:
            continue
        tolerance = max(
            3,
            median_gap * 0.30
        )
        consistent = (
            (gaps - median_gap).abs()
            <= tolerance
        ).mean()
        if consistent < 0.60:
            continue
        has_description_rule = any(
            rule.get("category", "").lower() == category
            and rule.get("direction", "").lower() == direction
            for rule in description_rules
        )
        if has_description_rule:
            continue
        recent_dates = dates[-3:]
        recent_amounts = [
            float(daily.loc[d])
            for d in recent_dates
        ]
        recurring.append({
            "scope": "category",
            "description": "",
            "category": category,
            "direction": direction,
            "flexibility": str(
                group["flexibility"].iloc[-1]
            ).lower(),
            "median_gap": int(
                round(median_gap)
            ),
            "amount": float(
                pd.Series(recent_amounts).median()
            ),
            "last_date": dates[-1].normalize(),
        })
    return recurring
def build_forecast(
    data,
    user_id,
    request_date,
    days=90
):
    profile = get_profile(
        data,
        user_id
    )
    message_rates = prepare_exchange_rates(
    data["rates"]
    )
    starting_balance = float(
        profile["current_available_balance"]
    )
    minimum_balance = float(
        profile["minimum_balance_to_keep"]
    )
    request_date = pd.Timestamp(
        request_date
    ).normalize()
    end_date = (
        request_date
        + pd.Timedelta(days=days)
    )
    user_events = get_user_events(
        data,
        user_id
    )
    usable = user_events[
        user_events.apply(
            event_is_usable,
            axis=1
        )
    ].copy()
    future_events = usable[
        (usable["settlement_date"] > request_date)
        & (usable["settlement_date"] <= end_date)
    ].copy()
    history = usable[
        usable["settlement_date"] < request_date
    ].copy()
    recurring = detect_recurring_events(
        history
    )
    dates = pd.date_range(
        start=request_date,
        end=end_date,
        freq="D"
    )
    daily_change = {
        date: 0.0
        for date in dates
    }
    pending_debit_reservation = 0.0
    for _, event in future_events.iterrows():
        amount = float(event["amount"])
        direction = str(
            event["direction"]
        ).lower()
        status = str(
            event["status"]
        ).lower()
        date = event["settlement_date"]
        if status == "pending" and direction == "debit":
            pending_debit_reservation += amount
        if status == "pending" and direction == "credit":
            continue
        if direction == "credit":
            daily_change[date] += amount
        elif direction == "debit":
            if status != "pending":
                daily_change[date] -= amount
    starting_balance -= pending_debit_reservation
    existing_description_pairs = set(
        zip(
            future_events["description"].astype(str),
            future_events["settlement_date"]
        )
    )
    existing_category_pairs = set(
        zip(
            future_events["category"]
            .astype(str)
            .str.lower(),
            future_events["settlement_date"]
        )
    )
    forecasted_description_pairs = set()
    forecasted_category_pairs = set()
    for item in recurring:
        gap = int(
            item["median_gap"]
        )
        if gap <= 0:
            continue
        scope = str(
            item.get("scope", "description")
        ).lower()
        description = str(
            item.get("description", "")
        )
        category = str(
            item.get("category", "")
        ).lower()
        amount = float(
            item["amount"]
        )
        direction = str(
            item["direction"]
        ).lower()
        next_date = (
            item["last_date"]
            + pd.Timedelta(days=gap)
        ).normalize()
        while next_date <= end_date:
            if next_date > request_date:
                description_key = (
                    description,
                    next_date
                )
                category_key = (
                    category,
                    next_date
                )
                should_add = False
                if scope == "description":
                    if (
                        description_key
                        not in existing_description_pairs
                        and description_key
                        not in forecasted_description_pairs
                    ):
                        should_add = True
                elif scope == "category":
                    if (
                        category_key
                        not in existing_category_pairs
                        and category_key
                        not in forecasted_category_pairs
                    ):
                        should_add = True
                if should_add:
                    if direction == "credit":
                        daily_change[next_date] += amount
                    elif direction == "debit":
                        daily_change[next_date] -= amount
                    if scope == "description":
                        forecasted_description_pairs.add(
                            description_key
                        )
                    elif scope == "category":
                        forecasted_category_pairs.add(
                            category_key
                        )
            next_date += pd.Timedelta(
                days=gap
            )
    salary_events = usable[
        (usable["category"].str.lower() == "salary")
        & (usable["direction"].str.lower() == "credit")
        & (usable["settlement_date"] <= request_date)
    ].sort_values("settlement_date")
    if not salary_events.empty:
        latest_salary = salary_events.iloc[-1]
        default_salary_amount = float(
            latest_salary["amount"]
        )
        salary_changes = []
        salary_date_changes = []
        one_time_salary_adjustments = []
        salary_ended = False
        user_messages = data["messages"][
            data["messages"]["user_id"].astype(str)
            == str(user_id)
        ].copy()
        user_messages = user_messages.sort_values("sent_at").copy()
        for _, message in user_messages.iterrows():
            text = str(
                message.get("message_text", "")
            ).strip()
            text_lower = text.lower()
            sent_at = pd.to_datetime(
                message.get("sent_at"),
                errors="coerce",
                utc=True
            )
            if pd.isna(sent_at):
                continue
            sent_at = (
                sent_at
                .tz_localize(None)
                .normalize()
            )
            is_payroll = any(
                keyword in text_lower
                for keyword in [
                    "salary",
                    "gaji",
                    "payroll",
                    "payroll team",
                    "monthly pay",
                    "monthly salary",
                    "base salary"
                ]
            )
            if not is_payroll:
                continue
            employment_ended = any(
                phrase in text_lower
                for phrase in [
                    "employment has ended",
                    "employment ended",
                    "seasonal contract has ended",
                    "seasonal contract ended",
                    "current seasonal contract has ended",
                    "one household employment record has ended",
                    "one household employment record ended",
                    "hubungan kerja anda telah berakhir",
                    "kontrak musiman saat ini telah berakhir",
                    "kontrak musiman telah berakhir",
                    "sumber pendapatan kerja rumah tangga telah berakhir"
                ]
            )
            if employment_ended:
                salary_ended = True
                continue
            salary_match = re.search(
                r"(?i)\b(IDR|INR|USD|EUR|ZAR)\s*"
                r"([0-9][0-9,]*(?:\.[0-9]+)?)",
                text
            )
            salary_amount = None
            salary_currency = None
            if salary_match:
                salary_currency = (
                    salary_match.group(1)
                    .strip()
                    .upper()
                )
                amount_text = (
                    salary_match.group(2)
                    .replace(",", "")
                )
                try:
                    salary_amount = float(
                        amount_text
                    )
                except ValueError:
                    salary_amount = None
            date_match = pd.Series([text]).str.extract(
                r"\b(20\d{2}-\d{2}-\d{2})\b",
                expand=False
            ).iloc[0]
            explicit_date = None
            if not pd.isna(date_match):
                try:
                    explicit_date = pd.Timestamp(
                        date_match
                    ).normalize()
                except Exception:
                    explicit_date = None
            if (
                salary_amount is not None
                and salary_currency is not None
            ):
                home_currency = str(
                    profile["home_currency"]
                ).strip().upper()
                conversion_date = (
                    explicit_date
                    if explicit_date is not None
                    else sent_at
                )
                rate = get_exchange_rate(
                    message_rates,
                    salary_currency,
                    home_currency,
                    conversion_date
                )
                if rate is None:
                    raise ValueError(
                        f"Missing exchange rate for salary message: "
                        f"{salary_currency} -> {home_currency} "
                        f"on {conversion_date.strftime('%Y-%m-%d')}"
                    )
                salary_amount *= rate
            pending_variable_income = any(
                phrase in text_lower
                for phrase in [
                    "bonus is still subject",
                    "bonus ... not been approved",
                    "final amount and payment date have not been approved",
                    "commission ... pending approval",
                    "commission shown for open deals",
                    "open deals will stay out of the payout",
                    "belum disetujui",
                    "jumlah akhir dan tanggal pembayaran belum disetujui",
                    "transaksi yang masih berjalan belum disetujui"
                ]
            )
            if (
                pending_variable_income
                and salary_amount is None
            ):
                continue
            arrears_match = re.search(
                r"(?i)(?:arrears|tunggakan)"
                r".{0,80}?"
                r"(IDR|INR|USD|EUR|ZAR)\s*"
                r"([0-9][0-9,]*(?:\.[0-9]+)?)",
                text
            )
            if (
                arrears_match
                and explicit_date is not None
            ):
                try:
                    arrears_currency = (
                        arrears_match.group(1)
                        .strip()
                        .upper()
                    )
                    arrears_amount = float(
                        arrears_match.group(2)
                        .replace(",", "")
                    )
                    home_currency = str(
                        profile["home_currency"]
                    ).strip().upper()
                    rate = get_exchange_rate(
                        message_rates,
                        arrears_currency,
                        home_currency,
                        explicit_date
                    )
                    if rate is None:
                        raise ValueError(
                            f"Missing exchange rate for arrears: "
                            f"{arrears_currency} -> {home_currency} "
                            f"on {explicit_date.strftime('%Y-%m-%d')}"
                        )
                    arrears_amount *= rate
                    one_time_salary_adjustments.append({
                        "date": explicit_date,
                        "amount": arrears_amount
                    })
                except ValueError:
                    pass
            if salary_amount is None:
                date_change = any(
                    phrase in text_lower
                    for phrase in [
                        "expected on",
                        "confirmed salary is now expected",
                        "replaces the payroll date",
                        "confirmed credit date",
                        "confirmed for",
                        "credit date"
                    ]
                )
                if (
                    date_change
                    and explicit_date is not None
                ):
                    salary_date_changes.append(
                        explicit_date
                    )
                continue
            salary_change = True
            if salary_change:
                if explicit_date is not None:
                    effective_date = explicit_date
                else:
                    effective_date = (
                        latest_salary[
                            "settlement_date"
                        ]
                    ).normalize()
                    while effective_date <= sent_at:
                        effective_date = (
                            effective_date
                            + pd.DateOffset(months=1)
                        ).normalize()
                salary_changes.append({
                    "effective_date":
                        effective_date,
                    "amount":
                        salary_amount
                })
        salary_changes = sorted(
            salary_changes,
            key=lambda item:
                item["effective_date"]
        )
        if salary_date_changes:
            next_salary_override = max(
                salary_date_changes
            )
        else:
            next_salary_override = None
        salary_changes = sorted(
            salary_changes,
            key=lambda x: x["effective_date"]
        )
        existing_salary_dates = set(
            future_events[
                (future_events["category"].str.lower() == "salary")
                & (future_events["direction"].str.lower() == "credit")
            ]["settlement_date"]
        )
        if next_salary_override is not None:
            next_salary_date = (
                next_salary_override
            )
        else:
            next_salary_date = (
                latest_salary["settlement_date"]
                + pd.DateOffset(months=1)
            ).normalize()
        while next_salary_date <= end_date:
            if next_salary_date > request_date:
                if salary_ended:
                    break
                salary_amount = (
                    default_salary_amount
                )
                for change in salary_changes:
                    if (
                        change["effective_date"]
                        <= next_salary_date
                    ):
                        salary_amount = (
                            change["amount"]
                        )
                if (
                    next_salary_date
                    not in existing_salary_dates
                ):
                    daily_change[
                        next_salary_date
                    ] += salary_amount
                for adjustment in (
                    one_time_salary_adjustments
                ):
                    if (
                        adjustment["date"]
                        == next_salary_date
                    ):
                        daily_change[
                            next_salary_date
                        ] += adjustment["amount"]
            next_salary_date = (
                next_salary_date
                + pd.DateOffset(months=1)
            ).normalize()
    rows = []
    balance = starting_balance
    for date in dates:
        if date > request_date:
            balance += daily_change[date]
        rows.append({
            "date": date,
            "balance": balance
        })
    forecast = pd.DataFrame(rows)
    return (
        forecast,
        minimum_balance
    )
def calculate_safe_amount(
    data,
    request
):
    user_id = request["user_id"]
    request_date = pd.Timestamp(
        request["request_date"]
    ).normalize()
    requested_amount = float(
        request["requested_amount"]
    )
    forecast, minimum_balance = (
        build_forecast(
            data,
            user_id,
            request_date
        )
    )
    worst_future_balance = float(
        forecast["balance"].min()
    )
    safe_amount = (
        worst_future_balance
        - minimum_balance
    )
    safe_amount = max(
        0.0,
        min(
            requested_amount,
            safe_amount
        )
    )
    return (
        safe_amount,
        forecast,
        minimum_balance
    )
def earliest_full_payment(
    forecast,
    minimum_balance,
    requested_amount
):
    requested_amount = float(
        requested_amount
    )
    for index in range(
        len(forecast)
    ):
        future_balances = (
            forecast.iloc[index:]["balance"]
        )
        lowest_future = float(
            future_balances.min()
        )
        if (
            lowest_future
            - requested_amount
            >= minimum_balance
        ):
            return forecast.iloc[index]["date"]
    return None
def test_sample_requests(data):
    samples = pd.read_csv(
        BASE / "sample_requests.csv"
    )
    samples = prepare_requests(samples)
    print("\nSAMPLE TEST")
    print("-" * 70)
    for _, request in samples.iterrows():
        try:
            safe_amount, _, _ = calculate_safe_amount(
                data,
                request
            )
            expected = float(
                request["amount_safe_to_pay"]
            )
            error = safe_amount - expected
            print(
                f"{request['request_id']:12}"
                f" expected={expected:12.2f}"
                f" ours={safe_amount:12.2f}"
                f" error={error:12.2f}"
            )
        except Exception as e:
            print(
                request["request_id"],
                "ERROR:",
                e
            )
def get_payment_options_for_request(data, request_id):
    options = data["options"]
    return options[
        options["request_id"].astype(str) == str(request_id)
    ].copy()
def prepare_payment_options(options):
    options = options.copy()
    options["payment_amount"] = pd.to_numeric(
        options["payment_amount"],
        errors="coerce"
    )
    options["number_of_payments"] = pd.to_numeric(
        options["number_of_payments"],
        errors="coerce"
    )
    options["first_payment_date"] = (
        pd.to_datetime(
            options["first_payment_date"],
            errors="coerce"
        )
        .dt.normalize()
    )
    options["payment_frequency_days"] = pd.to_numeric(
        options["payment_frequency_days"],
        errors="coerce"
    )
    options["total_payable_amount"] = pd.to_numeric(
        options["total_payable_amount"],
        errors="coerce"
    )
    return options
def build_payment_schedule(option):
    number_of_payments = int(
        option["number_of_payments"]
    )
    first_date = pd.Timestamp(
        option["first_payment_date"]
    ).normalize()
    amount = float(
        option["payment_amount"]
    )
    method = str(
        option["payment_method"]
    ).strip().lower()
    if method == "partial_payment":
        return option.get("partial_schedule", [])
    if method == "full_payment":
        return [(first_date, amount)]
    if method == "full_payment":
        return [(first_date, amount)]
    frequency = int(
        round(
            float(option["payment_frequency_days"])
        )
    )
    if frequency <= 0:
        return []
    schedule = []
    for i in range(number_of_payments):
        payment_date = (
            first_date
            + pd.Timedelta(days=i * frequency)
        ).normalize()
        schedule.append(
            (payment_date, amount)
        )
    return schedule
def format_payment_plan(option):
    schedule = build_payment_schedule(option)
    return "|".join(
        f"{date.strftime('%Y-%m-%d')}:{amount:.2f}"
        for date, amount in schedule
    )
def determine_affordability_status(
    requested_amount,
    safe_amount,
    best_option,
    earliest_full_payment_date
):
    requested_amount = float(requested_amount)
    safe_amount = float(safe_amount)
    if (
        safe_amount >= requested_amount
        and best_option is not None
        and str(
            best_option["payment_method"]
        ).strip().lower()
        == "full_payment"
    ):
        return "affordable_now"
    if best_option is not None:
        return "affordable_with_plan"
    if earliest_full_payment_date is not None:
        return "affordable_later"
    return "not_affordable"
def make_financial_decision(data, request):
    safe_amount, forecast, minimum_balance = (
        calculate_safe_amount(
            data,
            request
        )
    )
    earliest = earliest_full_payment(
        forecast,
        minimum_balance,
        request["requested_amount"]
    )
    best_option = choose_best_payment_option(
        data, safe_amount, request, forecast, minimum_balance, earliest
    )
    status = determine_affordability_status(
        request["requested_amount"],
        safe_amount,
        best_option,
        earliest
    )
    if best_option is None:
        if status == "not_affordable":
            recommended_method = "not_recommended"
        else:
            recommended_method = "wait"
        payment_plan = "none"
    else:
        recommended_method = str(
            best_option["payment_method"]
        ).strip().lower()
        payment_plan = format_payment_plan(
            best_option
        )
    spending_changes = "none"
    if safe_amount < float(request["requested_amount"]):
        user_events = prepare_events(
            get_user_events(
                data,
                request["user_id"]
            )
        )
        history = user_events[
            user_events["settlement_date"]
            < request["request_date"]
        ].copy()
        recurring = detect_recurring_events(
            history
        )
        flexible_rules = [
            item
            for item in recurring
            if str(
                item.get("flexibility", "")
            ).lower()
            in {
                "reducible",
                "stoppable",
                "reducible_or_stoppable",
            }
            and str(
                item.get("direction", "")
            ).lower()
            == "debit"
        ]
    if (
        best_option is None
        and earliest is None
        and flexible_rules
    ):
        spending_changes = "none"
    requested = float(
        request["requested_amount"]
    )
    if status == "affordable_now":
        decision_explanation = (
            f"Safe to pay the full requested amount of "
            f"{requested:.2f} now while maintaining the "
            f"required minimum balance."
        )
    elif status == "affordable_with_plan":
        decision_explanation = (
            f"Only {safe_amount:.2f} is safe today. "
            f"The selected payment plan completes the "
            f"purchase within the allowed period while "
            f"maintaining the required minimum balance."
        )
    elif status == "affordable_later":
        date_text = (
            earliest.strftime("%Y-%m-%d")
            if earliest is not None
            else "a later date"
        )
        decision_explanation = (
            f"The requested amount is not safely affordable "
            f"today. Full payment becomes financially feasible "
            f"on {date_text}."
        )
    else:
        decision_explanation = (
            "The requested amount cannot be safely afforded "
            "within the available forecast period."
        )
    return {
        "request_id": str(
            request["request_id"]
        ),
        "amount_safe_to_pay": round(
            safe_amount,
            2
        ),
        "affordability_status": status,
        "recommended_payment_method":
            recommended_method,
        "payment_plan":
            payment_plan,
        "earliest_date_for_full_payment": (
            earliest.strftime("%Y-%m-%d")
            if earliest is not None
            else "none"
        ),
        "spending_changes_needed":
            spending_changes,
        "decision_explanation":
            decision_explanation,
    }
def user_accepts_payment_method(profile, payment_method):
    allowed = str(
        profile["payment_methods_user_will_consider"]
    ).strip()
    if not allowed or allowed.lower() == "nan":
        return False
    methods = {
        item.strip().lower()
        for item in allowed.split("|")
        if item.strip()
    }
    return payment_method.lower().strip() in methods
def installment_limit_allows(profile, option):
    method = str(
        option["payment_method"]
    ).strip().lower()
    if method != "installments":
        return True
    max_months = profile["max_installment_months"]
    if pd.isna(max_months):
        return False
    schedule = build_payment_schedule(option)
    if not schedule:
        return False
    first_date = schedule[0][0]
    last_date = schedule[-1][0]
    duration_days = (
        last_date - first_date
    ).days
    duration_months = duration_days / 30.0
    return duration_months <= float(max_months)
def payment_option_is_safe(
    option,
    forecast,
    minimum_balance
):
    schedule = build_payment_schedule(option)
    if not schedule:
        return False
    balances = forecast.set_index("date")["balance"]
    cumulative_paid = 0.0
    for payment_date, payment_amount in schedule:
        if payment_date not in balances.index:
            return False
        cumulative_paid += float(payment_amount)
        balance_after_all_payments = (
            float(balances.loc[payment_date])
            - cumulative_paid
        )
        if balance_after_all_payments < minimum_balance:
            return False
    return True
def choose_best_payment_option(
    data,
    safe_amount,
    request,
    forecast,
    minimum_balance,
    earliest
):
    profile = get_profile(
        data,
        request["user_id"]
    )
    options = get_payment_options_for_request(
        data,
        request["request_id"]
    )
    options = prepare_payment_options(
        options
    )
    valid_options = []
    for _, option in options.iterrows():
        if not user_accepts_payment_method(
            profile,
            option["payment_method"]
        ):
            continue
        if not installment_limit_allows(
            profile,
            option
        ):
            continue
        schedule = build_payment_schedule(option)
        if not schedule:
            continue
        desired_date = pd.Timestamp(
            request["desired_completion_date"]
        ).normalize()
        last_payment_date = pd.Timestamp(
            schedule[-1][0]
        ).normalize()
        if (
            pd.notna(desired_date)
            and last_payment_date > desired_date
        ):
            continue
        if (
            str(option["payment_method"]).strip().lower()
            == "full_payment"
            and abs(
                float(option["payment_amount"])
                - float(request["requested_amount"])
            ) > 0.01
        ):
            continue
        if (
            str(option["payment_method"]).strip().lower()
            == "full_payment"
            and safe_amount < float(
                request["requested_amount"]
            )
        ):
            continue
        if not payment_option_is_safe(
            option,
            forecast,
            minimum_balance,
        ):
            continue
        valid_options.append(option)
    partial_allowed = (
        "partial_payment"
        in {
            str(method).strip().lower()
            for method in options["payment_method"].dropna()
        }
    )
    if (
        partial_allowed
        and user_accepts_payment_method(
            profile,
            "partial_payment"
        )
        and safe_amount > 0
        and safe_amount < float(request["requested_amount"])
        and earliest is not None
    ):
        desired_date = pd.Timestamp(
            request["desired_completion_date"]
        ).normalize()
        partial_completion = pd.Timestamp(
            earliest
        ).normalize()
        if (
            pd.isna(desired_date)
            or partial_completion <= desired_date
        ):
            remainder = (
                float(request["requested_amount"])
                - float(safe_amount)
            )
            partial_option = {
                "payment_method": "partial_payment",
                "payment_amount": float(safe_amount),
                "total_payable_amount": float(
                    request["requested_amount"]
                ),
                "number_of_payments": 2,
                "first_payment_date": pd.Timestamp(
                    request["request_date"]
                ).normalize(),
                "payment_frequency_days": 0,
                "partial_schedule": [
                    (
                        pd.Timestamp(
                            request["request_date"]
                        ).normalize(),
                        float(safe_amount)
                    ),
                    (
                        partial_completion,
                        float(remainder)
                    ),
                ],
            }
            if payment_option_is_safe(
                partial_option,
                forecast,
                minimum_balance
            ):
                valid_options.append(partial_option)
    if not valid_options:
        return None
    valid_options = pd.DataFrame(
        valid_options
    )
    valid_options = valid_options.sort_values(
        by=[
            "total_payable_amount",
            "number_of_payments",
            "first_payment_date"
        ],
        ascending=[
            True,
            True,
            True
        ]
    )
    return valid_options.iloc[0]
def main():
    data = load_data()
    data["events"] = prepare_events(
    data["events"]
    )
    data["events"] = recover_missing_event_amounts(
        data["events"],
        data["images"]
    )
    data["messages"] = prepare_messages(
        data["messages"]
    )
    data["events"] = apply_message_event_updates(
        data["events"],
        data["messages"]
    )
    data["events"] = convert_events_to_home_currency(
        data["events"],
        data["profiles"],
        data["rates"]
    )
    data["requests"] = prepare_requests(
        data["requests"]
    )
    print("DATA LOADED")
    print(
        f"Requests: {len(data['requests'])}"
    )
    print(
        f"Events: {len(data['events'])}"
    )
    results = []
    for _, request in data["requests"].iterrows():
        try:
            decision = make_financial_decision(
                data,
                request
            )
            results.append(
                decision
            )
        except Exception as error:
            raise RuntimeError(
                f"Failed to process "
                f"{request['request_id']}: {error}"
            ) from error
    output_columns = [
        "request_id",
        "amount_safe_to_pay",
        "affordability_status",
        "recommended_payment_method",
        "payment_plan",
        "earliest_date_for_full_payment",
        "spending_changes_needed",
        "decision_explanation",
    ]
    output = pd.DataFrame(
        results,
        columns=output_columns
    )
    output.to_csv(
        BASE.parent / "output.csv",
        index=False
)
    print("\nOUTPUT CREATED")
    print(
        "Rows:",
        len(output)
    )
    print(
        "File:",
        BASE.parent / "output.csv"
    )
if __name__ == "__main__":
    main()
