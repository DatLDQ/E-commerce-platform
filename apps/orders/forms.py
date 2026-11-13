import re

from django import forms

from apps.accounts.models import phone_validator

from .models import DeliveryMethod, Order
from .services import PROVINCES, normalize_province

# Vietnamese tax code: 10 digits for a company, 13 (10 + "-" + 3) for a dependent branch.
TAX_CODE_RE = re.compile(r"\d{10}(-?\d{3})?")


class CheckoutForm(forms.Form):
    def __init__(self, data=None, *args, **kwargs):
        # Saved addresses may still hold a pre-reform province name.
        initial = kwargs.get("initial") or {}
        if initial.get("province"):
            initial["province"] = normalize_province(initial["province"])
        super().__init__(data, *args, **kwargs)
        # Only offer methods that can actually be paid in this deployment
        # (e.g. no MoMo/VNPay when the simulator is off and no merchant keys).
        from apps.payments.gateway import available_payment_methods

        allowed = set(available_payment_methods())
        self.fields["payment_method"].choices = [c for c in Order.PaymentMethod.choices if c[0] in allowed]

    full_name = forms.CharField(label="Họ và tên", max_length=120)
    email = forms.EmailField(label="Email")
    phone = forms.CharField(label="Số điện thoại", max_length=15, validators=[phone_validator])
    province = forms.ChoiceField(label="Tỉnh / Thành phố", choices=[(p, p) for p in PROVINCES])
    # Since 1/7/2025 Vietnam uses province -> ward/commune (no district level).
    ward = forms.CharField(label="Phường / Xã / Đặc khu", max_length=60)
    street = forms.CharField(label="Số nhà, tên đường", max_length=200)
    note = forms.CharField(label="Ghi chú cho shipper", max_length=300, required=False, widget=forms.Textarea(attrs={"rows": 2}))
    delivery_method = forms.ModelChoiceField(
        label="Phương thức giao hàng", queryset=DeliveryMethod.objects.filter(is_active=True), widget=forms.RadioSelect, empty_label=None
    )
    payment_method = forms.ChoiceField(label="Phương thức thanh toán", choices=Order.PaymentMethod.choices, widget=forms.RadioSelect)
    want_vat_invoice = forms.BooleanField(label="Xuất hoá đơn VAT cho công ty", required=False)
    vat_company = forms.CharField(label="Tên công ty", max_length=200, required=False)
    vat_tax_code = forms.CharField(label="Mã số thuế", max_length=20, required=False)
    save_address = forms.BooleanField(label="Lưu địa chỉ này cho lần sau", required=False, initial=True)
    agree_terms = forms.BooleanField(
        label="Tôi đã đọc và đồng ý với Điều khoản mua hàng, Chính sách đổi trả và Chính sách bảo mật",
        error_messages={"required": "Bạn cần đồng ý với điều khoản để đặt hàng."},
    )

    def clean_vat_tax_code(self):
        return self.cleaned_data.get("vat_tax_code", "").strip().replace(" ", "")

    def clean(self):
        data = super().clean()
        method, province = data.get("delivery_method"), data.get("province")
        if method and province and not method.available_for(province):
            self.add_error("delivery_method", f"{method.name} chưa hỗ trợ khu vực {province}.")
        if data.get("want_vat_invoice"):
            if not (data.get("vat_company") and data.get("vat_tax_code")):
                self.add_error("vat_tax_code", "Vui lòng nhập tên công ty và mã số thuế để xuất hoá đơn.")
            elif not TAX_CODE_RE.fullmatch(data["vat_tax_code"]):
                self.add_error("vat_tax_code", "Mã số thuế gồm 10 chữ số, hoặc 13 chữ số với đơn vị phụ thuộc (VD: 0123456789 hoặc 0123456789-001).")
        if method and method.is_pickup and data.get("payment_method") == Order.PaymentMethod.COD:
            pass  # pay at the counter — allowed
        return data


class OrderLookupForm(forms.Form):
    code = forms.CharField(label="Mã đơn hàng", max_length=20)
    contact = forms.CharField(label="Email hoặc số điện thoại đặt hàng", max_length=120)
