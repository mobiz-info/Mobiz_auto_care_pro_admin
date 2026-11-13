import io
import re
import html
import requests
from django.utils import timezone

# 12 Active templates used in Mobiz Car Wash codebase
ACTIVE_SYSTEM_TEMPLATES = [
    {
        'key': 'welcome1',
        'template_name': 'Customer Welcome',
        'wawy_template_name': 'welcome1',
        'category': '12',  # UTILITY / TRANSACTIONAL
        'category_name': 'UTILITY / TRANSACTIONAL',
        'msgtype': '1',    # Text
        'content': 'Hi {{1}} Welcome to {{2}}.Your vehicle {{3}} has arrived safely and is in expert hands.We will keep you posted!',
        'footer': '',
        'samples': {
            'param15': 'Rahul',
            'param16': 'Mobiz Auto Care',
            'param17': 'KL 07 AX 1234',
        },
        'description': 'Triggered on customer/vehicle arrival at service center.'
    },
    {
        'key': 'ready1',
        'template_name': 'Vehicle Ready Alert',
        'wawy_template_name': 'ready1',
        'category': '12',
        'category_name': 'UTILITY / TRANSACTIONAL',
        'msgtype': '1',
        'content': 'Hi {{1}} Great news! Your vehicle {{2}} is ready for pickup. Please collect at your earliest convenience.{{3}} Support team.',
        'footer': '',
        'samples': {
            'param15': 'Rahul',
            'param16': 'KL 07 AX 1234',
            'param17': 'Mobiz Auto Care',
        },
        'description': 'Sent when job card or washing is completed and vehicle is ready for pickup.'
    },
    {
        'key': 'thanks1',
        'template_name': 'Thank You Message',
        'wawy_template_name': 'thanks1',
        'category': '12',
        'category_name': 'UTILITY / TRANSACTIONAL',
        'msgtype': '1',
        'content': 'Dear {{1}} 🙏 Thank you for trusting us with your vehicle {{2}}. We hope you had a great experience. Looking forward to seeing you again!{{3}} support team.',
        'footer': '',
        'samples': {
            'param15': 'Rahul',
            'param16': 'KL 07 AX 1234',
            'param17': 'Mobiz Auto Care',
        },
        'description': 'Sent upon vehicle delivery / payment confirmation.'
    },
    {
        'key': 'invoice',
        'template_name': 'Tax Invoice with PDF',
        'wawy_template_name': 'invoice',
        'category': '12',
        'category_name': 'UTILITY / TRANSACTIONAL',
        'msgtype': '2',    # Document
        'content': 'Dear {{1}},Your invoice *{{2}}* has been generated successfully at {{3}}.*Invoice Details:*Vehicle: {{4}}Services:{{5}}Total: {{6}}Paid: {{7}}Balance: {{8}}Please find the attached PDF invoice for your reference.Thank you for choosing us!',
        'footer': '',
        'samples': {
            'param15': 'Rahul',
            'param16': 'INV-1001',
            'param17': 'Mobiz Auto Care',
            'param18': 'KL 07 AX 1234',
            'param19': 'Full Foam Wash',
            'param20': '500',
            'param21': '500',
            'param22': '0',
        },
        'description': 'Sends detailed tax invoice with downloadable PDF attachment.'
    },
    {
        'key': 'alignmentinvoicemsg',
        'template_name': 'Wheel Alignment Alert',
        'wawy_template_name': 'alignmentinvoicemsg',
        'category': '12',
        'category_name': 'UTILITY / TRANSACTIONAL',
        'msgtype': '1',
        'content': 'Dear {{1}} your vehicle {{2}} is ready at {{3}} km you need to do the next {{4}} service. Thank you for choosing {{5}} team',
        'footer': '',
        'samples': {
            'param15': 'Rahul',
            'param16': 'KL 07 AX 1234',
            'param17': '45000',
            'param18': 'Wheel Alignment',
            'param19': 'Mobiz Auto Care',
        },
        'description': 'Sent after wheel alignment/balancing with next service kilometer alert.'
    },
    {
        'key': 'detailinginvoicemsg',
        'template_name': 'Detailing Top-up Alert',
        'wawy_template_name': 'detailinginvoicemsg',
        'category': '12',
        'category_name': 'UTILITY / TRANSACTIONAL',
        'msgtype': '1',
        'content': 'Dear {{1}} your vehicle {{2}} is ready. Kindly visit us after {{3}} days for the next  top up service. Thank you for choosing {{4}} team.',
        'footer': '',
        'samples': {
            'param15': 'Rahul',
            'param16': 'KL 07 AX 1234',
            'param17': '90',
            'param18': 'Mobiz Auto Care',
        },
        'description': 'Sent after ceramic/detailing coating with next top-up inspection reminder.'
    },
    {
        'key': 'quotation',
        'template_name': 'Quotation Estimate with PDF',
        'wawy_template_name': 'quotation',
        'category': '12',
        'category_name': 'UTILITY / TRANSACTIONAL',
        'msgtype': '2',    # Document
        'content': 'Dear {{1}} Please find the quotation. Awaiting your order confirmation.Thanks and Regards',
        'footer': '',
        'samples': {
            'param15': 'Rahul',
        },
        'description': 'Sends vehicle service quotation estimate with attached PDF.'
    },
    {
        'key': 'servicesreminder',
        'template_name': 'Periodic Service Reminder',
        'wawy_template_name': 'servicesreminder',
        'category': '12',
        'category_name': 'UTILITY / TRANSACTIONAL',
        'msgtype': '1',
        'content': 'Dear {{1}}, your vehicle {{2}} is due for its next {{3}} service. Kindly plan your visit as early as possible',
        'footer': '',
        'samples': {
            'param15': 'Rahul',
            'param16': 'KL 07 AX 1234',
            'param17': 'General Maintenance',
        },
        'description': 'Automated periodic maintenance reminder.'
    },
    {
        'key': 'oilreminder',
        'template_name': 'Engine Oil Change Reminder',
        'wawy_template_name': 'oilreminder',
        'category': '12',
        'category_name': 'UTILITY / TRANSACTIONAL',
        'msgtype': '1',
        'content': 'Dear {{1}} your vehicle no {{2}} next oil change to be done on {{3}} km',
        'footer': '',
        'samples': {
            'param15': 'Rahul',
            'param16': 'KL 07 AX 1234',
            'param17': '50000',
        },
        'description': 'Sent to remind customer for timely engine oil replacement.'
    },
    {
        'key': 'batteryservice',
        'template_name': 'Battery Health & AMC Checkup',
        'wawy_template_name': 'batteryservice',
        'category': '12',
        'category_name': 'UTILITY / TRANSACTIONAL',
        'msgtype': '1',
        'content': 'Dear {{1}}, tomorrow we are planning to visit your place for providing {{2}} as a part of our amc  contract for battery health check up. We request you to kindly confirm your availability. If any inconvenience please let us know.',
        'footer': '',
        'samples': {
            'param15': 'Rahul',
            'param16': 'Battery Health Inspection',
        },
        'description': 'Notification for on-site battery health inspection and AMC visit.'
    },
    {
        'key': 'smoketest',
        'template_name': 'Pollution Certificate Expiry',
        'wawy_template_name': 'smoketest',
        'category': '12',
        'category_name': 'UTILITY / TRANSACTIONAL',
        'msgtype': '1',
        'content': 'Dear {{1}}, your vehicle no {{2}} pollution certificate is getting expired on {{3}}.  Kindly renew',
        'footer': '',
        'samples': {
            'param15': 'Rahul',
            'param16': 'KL 07 AX 1234',
            'param17': '30-11-2026',
        },
        'description': 'Smoke test / PUCC certificate expiry alert.'
    },
    {
        'key': 'festivalgreeting',
        'template_name': 'Festival & Special Offers',
        'wawy_template_name': 'festivalgreeting',
        'category': '13',  # PROMOTIONAL / MARKETING
        'category_name': 'PROMOTIONAL / MARKETING',
        'msgtype': '1',
        'content': 'Hello Dear {{1}}, Wishing you and your family a very Happy {{2}}! Warm wishes from {{3}} Team.',
        'footer': '',
        'samples': {
            'param15': 'Rahul',
            'param16': 'Onam',
            'param17': 'Mobiz Auto Care',
        },
        'description': 'Bulk festival greetings and promotional campaigns to customers.'
    },
]

DUMMY_PDF_BYTES = (
    b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n'
    b'2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n'
    b'3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n'
    b'xref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000052 00000 n\n'
    b'00000101 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n178\n%%EOF\n'
)


def clean_phone_for_wawy(phone_str):
    if not phone_str:
        return ''
    cleaned = re.sub(r'\D', '', str(phone_str))
    if len(cleaned) == 10:
        cleaned = '91' + cleaned
    elif len(cleaned) == 9 and not cleaned.startswith('971'):
        cleaned = '971' + cleaned
    return cleaned


class WawyClient:
    BASE_URL = 'http://wawy.org'

    def __init__(self, username='mobiz', password='Mobiz123@'):
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.is_authenticated = False

    def login(self):
        try:
            login_data = {
                'txtUser': self.username,
                'txtPassword': self.password,
                'check': 'ok',
                'forgot': '',
                'login': ''
            }
            resp = self.session.post(f"{self.BASE_URL}/index.php", data=login_data, timeout=15)
            # If username is found in response, login is successful
            if self.username.lower() in resp.text.lower():
                self.is_authenticated = True
                return True, "Login successful"
            else:
                return False, "Invalid username or password on Wawy portal"
        except Exception as e:
            return False, f"Connection error to Wawy: {str(e)}"

    def get_senders(self):
        """
        Retrieves list of senders from Wawy portal.
        Returns: list of dicts [{'sender_id': '1-139', 'number': '919496007007', 'label': '...'}]
        """
        if not self.is_authenticated:
            ok, err = self.login()
            if not ok:
                return []

        try:
            r = self.session.get(f"{self.BASE_URL}/processes/linkcheck/wa_meta_template_l.php", timeout=15)
            senders = []
            sender_match = re.search(r'<select[^>]*name=["\']param1["\'][^>]*>(.*?)</select>', r.text, re.DOTALL | re.IGNORECASE)
            if sender_match:
                for opt_val, opt_text in re.findall(r'<option[^>]*value=["\']([^"\']+)["\'][^>]*>(.*?)</option>', sender_match.group(1), re.DOTALL | re.IGNORECASE):
                    val = opt_val.strip()
                    txt = html.unescape(re.sub(r'<[^>]+>', '', opt_text)).strip()
                    if val and val != '-1':
                        clean_num = clean_phone_for_wawy(txt)
                        senders.append({
                            'sender_id': val,
                            'number': clean_num or txt,
                            'label': txt
                        })
            return senders
        except Exception:
            return []

    def get_existing_templates(self):
        """
        Scrapes all existing templates on Wawy for this account.
        Returns dict: {template_name.lower(): {'status': 'APPROVED', 'raw': '...'}}
        """
        if not self.is_authenticated:
            ok, err = self.login()
            if not ok:
                return {}

        try:
            r = self.session.get(f"{self.BASE_URL}/processes/linkcheck/wa_meta_template_l.php", timeout=15)
            templates = {}
            for row_html in re.findall(r'<tr[^>]*>(.*?)</tr>', r.text, re.DOTALL | re.IGNORECASE):
                cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, re.DOTALL | re.IGNORECASE)
                tds = [html.unescape(re.sub(r'<[^>]+>', '', c)).strip() for c in cells]
                if len(tds) >= 3:
                    name_cell = tds[1]
                    m = re.match(r'^([a-zA-Z0-9_\-]+)\s*\((.*?)\)\s*\[(.*?)\]', name_cell)
                    if m:
                        t_name = m.group(1).lower()
                        t_cat = m.group(2)
                        t_status = m.group(3)
                        templates[t_name] = {
                            'name': t_name,
                            'category': t_cat,
                            'status': t_status,
                            'content': tds[2] if len(tds) > 2 else '',
                            'sender_number': tds[0] if len(tds) > 0 else ''
                        }
            return templates
        except Exception:
            return {}

    def submit_template(self, sender_id, template_dict):
        """
        Submits a single template to Wawy formcheck endpoint.
        """
        if not self.is_authenticated:
            ok, err = self.login()
            if not ok:
                return False, err

        tmpl_name = template_dict.get('wawy_template_name') or template_dict.get('template_name', '').lower().replace(' ', '')
        content = template_dict.get('content', '')
        category = template_dict.get('category', '12')
        msgtype = template_dict.get('msgtype', '1')
        language = template_dict.get('language', 'en')
        footer = template_dict.get('footer', '')

        post_data = {
            'param1': sender_id,
            'param2': tmpl_name,
            'param3': language,
            'param4': category,
            'param5': content,
            'param6': footer,
            'msgtype': msgtype,
        }

        # Check for media attachment
        files = None
        if str(msgtype) == '2':  # Document
            post_data['param7'] = '1'  # Enable media
            files = {
                'file': ('sample.pdf', DUMMY_PDF_BYTES, 'application/pdf')
            }
        elif str(msgtype) == '0':  # Image
            post_data['param7'] = '1'

        # Extract variable parameters {{1}}, {{2}}, etc. and set sample values
        samples = template_dict.get('samples', {})
        vars_found = re.findall(r'\{\{(\d+)\}\}', content)
        for var_idx_str in vars_found:
            idx = int(var_idx_str)
            param_key = f"param{14 + idx}"
            if param_key not in post_data:
                sample_val = samples.get(param_key) or f"Sample{idx}"
                post_data[param_key] = sample_val

        try:
            url = f"{self.BASE_URL}/processes/formcheck/wa_meta_template_f.php"
            if files:
                r = self.session.post(url, data=post_data, files=files, timeout=20)
            else:
                r = self.session.post(url, data=post_data, timeout=20)

            resp_text = r.text
            if "Already Exist" in resp_text:
                return True, "Already exists in Wawy"
            elif "alertsuccess" in resp_text or "successfully" in resp_text.lower():
                return True, "Submitted successfully to Meta for approval"
            elif "alertinfo" in resp_text:
                alert_match = re.search(r'<div[^>]*class=["\']alertinfo["\'][^>]*>(.*?)</div>', resp_text, re.DOTALL | re.IGNORECASE)
                msg = html.unescape(re.sub(r'<[^>]+>', '', alert_match.group(1))).strip() if alert_match else "Validation notice from Wawy"
                if "Already Exist" in msg:
                    return True, "Already exists in Wawy"
                return False, msg
            else:
                return True, "Request submitted to Wawy"
        except Exception as e:
            return False, f"Error submitting to Wawy: {str(e)}"


def deploy_active_templates_for_company(company, sender_id=None, override_wawy_client=None, wawy_username=None, wawy_password=None, save_setting=True):
    """
    Deploys the 12 active system templates for a given company:
    1. Submits templates to Wawy under the company's specific Wawy account.
    2. Inserts or updates all 12 templates into Django WhatsAppTemplate table for that company.
    """
    from client_management.models import WhatsAppSetting, WhatsAppTemplate
    from core.functions import get_auto_id

    # Find or create company setting
    setting = WhatsAppSetting.objects.filter(company=company).first()

    # Determine username and password to use:
    # 1. Explicitly passed in call
    # 2. Existing setting for this company
    # 3. Master default mobiz/Mobiz123@ as fallback
    wawy_user = (wawy_username or (setting.username if setting and setting.username else '')).strip()
    wawy_pass = (wawy_password or (setting.password if setting and setting.password else '')).strip()

    if not wawy_user or not wawy_pass:
        # Fall back to master mobiz account if no client-specific account provided
        wawy_user = wawy_user or 'mobiz'
        wawy_pass = wawy_pass or 'Mobiz123@'

    client = override_wawy_client
    ok = False
    login_msg = ''
    if not client:
        client = WawyClient(username=wawy_user, password=wawy_pass)
        ok, login_msg = client.login()

    if not ok:
        return {
            'company_id': str(company.id),
            'company_name': company.company_name,
            'success': False,
            'error': f"Failed to log in to Wawy with user '{wawy_user}': {login_msg}",
            'deployed_to_wawy': 0,
            'already_in_wawy': 0,
            'saved_to_db': 0,
            'details': []
        }

    senders = client.get_senders()
    existing_wawy_templates = client.get_existing_templates()

    # Determine sender_id
    chosen_sender_id = sender_id
    if not chosen_sender_id:
        if setting and setting.sender_id:
            s_clean = clean_phone_for_wawy(setting.sender_id)
            for s in senders:
                if s['sender_id'] == setting.sender_id or s['number'] == setting.sender_id or s['number'] == s_clean:
                    chosen_sender_id = s['sender_id']
                    break
        if not chosen_sender_id and company.phone:
            c_clean_phone = clean_phone_for_wawy(company.phone)
            for s in senders:
                if s['number'] == c_clean_phone or s['number'].endswith(c_clean_phone[-10:]):
                    chosen_sender_id = s['sender_id']
                    break
        if not chosen_sender_id and senders:
            chosen_sender_id = senders[0]['sender_id']

    # Save settings for this company if requested
    if save_setting:
        if not setting:
            setting = WhatsAppSetting(company=company, auto_id=get_auto_id(WhatsAppSetting))
        setting.username = wawy_user
        setting.password = wawy_pass
        if chosen_sender_id:
            setting.sender_id = chosen_sender_id
        if not setting.whatsapp_number and company.phone:
            setting.whatsapp_number = clean_phone_for_wawy(company.phone)
        if not setting.url:
            setting.url = 'http://wawy.org/pushwhatsapp.php'
        setting.save()

    results = {
        'company_id': str(company.id),
        'company_name': company.company_name,
        'sender_id': chosen_sender_id,
        'wawy_user': wawy_user,
        'success': True,
        'wawy_logged_in': ok,
        'deployed_to_wawy': 0,
        'already_in_wawy': 0,
        'saved_to_db': 0,
        'details': []
    }

    for tmpl in ACTIVE_SYSTEM_TEMPLATES:
        w_name = tmpl['wawy_template_name'].lower()
        detail = {
            'key': tmpl['key'],
            'name': tmpl['template_name'],
            'wawy_name': w_name,
            'category': tmpl['category_name'],
            'wawy_status': 'PENDING',
            'wawy_message': '',
            'db_status': 'SAVED'
        }

        # 1. Check / Deploy to Wawy
        if ok and chosen_sender_id:
            if w_name in existing_wawy_templates:
                detail['wawy_status'] = existing_wawy_templates[w_name]['status']
                detail['wawy_message'] = f"Already in Wawy ({detail['wawy_status']})"
                results['already_in_wawy'] += 1
            else:
                success, msg = client.submit_template(chosen_sender_id, tmpl)
                if success:
                    detail['wawy_status'] = 'SUBMITTED'
                    detail['wawy_message'] = msg
                    results['deployed_to_wawy'] += 1
                else:
                    detail['wawy_status'] = 'FAILED'
                    detail['wawy_message'] = msg
        else:
            detail['wawy_status'] = 'SKIPPED'
            detail['wawy_message'] = 'No Wawy sender ID or connection available'

        # 2. Save or Update in Django WhatsAppTemplate
        try:
            db_tmpl, created = WhatsAppTemplate.objects.get_or_create(
                company=company,
                wawy_template_name=w_name,
                is_deleted=False,
                defaults={
                    'auto_id': get_auto_id(WhatsAppTemplate),
                    'template_name': tmpl['template_name'],
                    'content': tmpl['content'],
                }
            )
            if not created:
                db_tmpl.content = tmpl['content']
                db_tmpl.template_name = tmpl['template_name']
                db_tmpl.save()

            results['saved_to_db'] += 1
            detail['db_status'] = 'CREATED' if created else 'UPDATED'
        except Exception as e:
            detail['db_status'] = f"ERROR: {str(e)}"

        results['details'].append(detail)

    return results
