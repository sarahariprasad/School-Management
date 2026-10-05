from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings

from branches.models import Branch
from students.models import Group, Student
from .forms import FeePaymentForm, StudentFeeAssignmentForm
from .models import FeeCategory, FeeInstallment, FeePayment, FeeStructure, Frequency, StudentFeeAssignment
from .views import FeePaymentCreateView


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class FeePaymentIntegrationTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code='MAIN', name='Main Centre')
        self.other_branch = Branch.objects.create(code='OTHER', name='Other Centre')
        self.group = Group.objects.create(name=Group.GREEN)
        self.other_group = Group.objects.create(name=Group.RED)
        self.student = Student.objects.create(
            student_id='STU-001', name='Aarav', date_of_birth=date(2018, 1, 1),
            gender='Male', group=self.group, student_branch=self.branch,
            mother_name='Mother', father_name='Father', address='Address',
        )
        self.category = FeeCategory.objects.create(name='Therapy Fee')

    def create_assignment(self, frequency=Frequency.MONTHLY, start_date=date(2026, 1, 15)):
        structure = FeeStructure.objects.create(
            branch=self.branch, group=self.group, category=self.category,
            academic_year='2026-2027', frequency=frequency,
            start_date=start_date, amount=Decimal('1000.00'),
        )
        return StudentFeeAssignment.objects.create(
            student=self.student, fee_structure=structure, final_amount=Decimal('1000.00')
        )

    def test_assignment_form_rejects_another_branch_or_group(self):
        wrong_structure = FeeStructure.objects.create(
            branch=self.other_branch, group=self.other_group, category=self.category,
            academic_year='2026-2027', amount=Decimal('1000.00'),
        )
        form = StudentFeeAssignmentForm(data={
            'student': self.student.pk, 'fee_structure': wrong_structure.pk,
            'discount_amount': '0', 'is_active': 'on',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('fee_structure', form.errors)

    def test_frequency_controls_the_next_due_date(self):
        assignment = self.create_assignment(Frequency.QUARTERLY)
        assignment.generate_installments()
        due_dates = list(assignment.installments.values_list('due_date', flat=True))
        self.assertEqual(len(due_dates), 2)
        self.assertEqual((due_dates[1].year - due_dates[0].year) * 12 + due_dates[1].month - due_dates[0].month, 3)

    def test_editing_or_deleting_payment_refreshes_paid_status(self):
        assignment = self.create_assignment()
        installment = FeeInstallment.objects.create(
            assignment=assignment, installment_number=1, amount_due=Decimal('100.00'), due_date=date.today()
        )
        payment = FeePayment.objects.create(installment=installment, amount_paid=Decimal('100.00'))
        installment.refresh_from_db()
        self.assertTrue(installment.is_fully_paid)

        # The original installment remains available during payment editing.
        form = FeePaymentForm(instance=payment, data={
            'installment': installment.pk, 'amount_paid': '60.00', 'mode': 'cash',
            'transaction_ref': '', 'remarks': '',
        })
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        installment.refresh_from_db()
        self.assertFalse(installment.is_fully_paid)

        payment.delete()
        installment.refresh_from_db()
        self.assertFalse(installment.is_fully_paid)

    def test_payment_form_rejects_overpayment_when_editing(self):
        assignment = self.create_assignment()
        installment = FeeInstallment.objects.create(
            assignment=assignment, installment_number=1, amount_due=Decimal('100.00'), due_date=date.today()
        )
        payment = FeePayment.objects.create(installment=installment, amount_paid=Decimal('40.00'))
        form = FeePaymentForm(instance=payment, data={
            'installment': installment.pk, 'amount_paid': '101.00', 'mode': 'cash',
            'transaction_ref': '', 'remarks': '',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('amount_paid', form.errors)

    def test_installment_payment_status_cannot_be_set_manually(self):
        assignment = self.create_assignment()
        installment = FeeInstallment.objects.create(
            assignment=assignment, installment_number=1, amount_due=Decimal('100.00'), due_date=date.today()
        )
        installment.is_fully_paid = True
        installment.save()
        installment.refresh_from_db()
        self.assertFalse(installment.is_fully_paid)

    def test_payment_link_prefills_an_eligible_installment(self):
        assignment = self.create_assignment()
        installment = FeeInstallment.objects.create(
            assignment=assignment, installment_number=1, amount_due=Decimal('100.00'), due_date=date.today()
        )
        view = FeePaymentCreateView()
        view.setup(RequestFactory().get(f'/fees/payments/add/?installment={installment.pk}'))
        self.assertEqual(view.get_initial()['installment'], str(installment.pk))

    def test_installment_becomes_overdue_only_after_the_tenth(self):
        assignment = self.create_assignment()
        installment = FeeInstallment.objects.create(
            assignment=assignment, installment_number=1, amount_due=Decimal('100.00'), due_date=date(2026, 10, 1)
        )

        class BeforeGraceDate(date):
            @classmethod
            def today(cls):
                return cls(2026, 10, 10)

        class AfterGraceDate(date):
            @classmethod
            def today(cls):
                return cls(2026, 10, 11)

        with patch('fee_payment.models.date', BeforeGraceDate):
            self.assertFalse(installment.is_overdue)
        with patch('fee_payment.models.date', AfterGraceDate):
            self.assertTrue(installment.is_overdue)
