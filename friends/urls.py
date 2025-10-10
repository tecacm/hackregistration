from django.urls import path

from friends import views

urlpatterns = [
    path('', views.JoinFriendsView.as_view(), name='join_friends'),
    path('invite/', views.FriendsListInvite.as_view(), name='invite_friends'),
    path('matchmaking/accept/<str:token>/', views.FriendsMergeOptInView.as_view(), name='friends_merge_opt_in'),
]
