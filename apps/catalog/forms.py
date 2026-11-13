from django import forms

from .models import Review


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["rating", "title", "comment"]
        labels = {"rating": "Số sao", "title": "Tiêu đề", "comment": "Nhận xét"}
        widgets = {
            "rating": forms.RadioSelect(choices=[(i, f"{i}★") for i in range(5, 0, -1)]),
            "comment": forms.Textarea(attrs={"rows": 4, "placeholder": "Cảm nhận về độ hoàn thiện, cảm giác sử dụng, độ trễ…"}),
        }
