from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('import_students/', views.import_student_excel, name='student-import'),
    path('import_fees/', views.import_fees_status, name='fees-import'),
    path(
        'import_offers/',
        views.import_offer_excel_view,
        name='offer-import'
    ),

    path('offers/<int:offer_id>/remove/', views.remove_offer, name='offer-remove'),
    path('offers/<int:offer_id>/admission_category/', views.update_offer_admission_category, name='offer-update-admission-category'),
    path('offers/<int:offer_id>/iitgn_email/', views.update_offer_iitgn_email, name='offer-update-iitgn-email'),
    path('offers/<int:offer_id>/roll_no/', views.update_offer_roll_no, name='offer-update-roll-no'),
    path('offers/<int:offer_id>/remarks/', views.update_offer_remarks, name='offer-update-remarks'),
    path('offers/<int:offer_id>/withdrawal/', views.update_offer_withdrawal, name='offer-update-withdrawal'),
    path('offers/<int:offer_id>/fees_deadline/', views.update_offer_fees_deadline, name='offer-update-fees-deadline'),
    path('offers/<int:offer_id>/date_of_joining/', views.update_offer_date_of_joining, name='offer-update-date-of-joining'),
    path('semesters/', views.semester_list, name='semester-list'),
    path('all_students/', views.student_list, name='student-list'),
    path('all_students/<int:student_id>/add_to_offers/', views.add_student_to_offers, name='student-add-to-offers'),
    path('semesters/<int:semester_id>/toggle_active/', views.toggle_semester_active, name='semester-toggle-active'),
    path('all_students/<int:student_id>/delete/', views.delete_student, name='student-delete'),
    path('all_students/<int:student_id>/edit/', views.edit_student, name='student-edit'),
    path('add_semester/', views.add_semester, name='semester-add'),
    path('faculty/', views.live_sheet, name='live-sheet'),
    path('faculty/account/', views.faculty_account, name='faculty-account'),
]
